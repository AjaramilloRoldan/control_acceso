import os
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from ..clock import hora_actual
from ..extensions import db
from ..models import ROLES_USUARIO, Dispositivo, Instalacion, Reserva
from ..notifications import describir_reserva, notificar
from ..permisos import deny_page
from ..security import log_security_event

bp = Blueprint('instalaciones', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ESTADOS_OPERATIVOS = ('activo', 'mantenimiento', 'fuera_servicio')
CAPACIDAD_MINIMA = 1
CAPACIDAD_MAXIMA = 500
MENSAJE_NOMBRE_REPETIDO = 'Error: Ya existe un espacio con ese nombre'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_roles(form):
    roles = form.getlist('roles_permitidos')
    if not roles or not set(roles) <= set(ROLES_USUARIO):
        return None, 'Error: Selecciona al menos un rol válido'
    return (None if set(roles) == set(ROLES_USUARIO) else ','.join(roles)), None

def read_space_fields(form):
    campos = {
        'nombre': form.get('nombre', '').strip(),
        'ubicacion': form.get('ubicacion', '').strip(),
        'dotacion': form.get('dotacion', '').strip(),
        'capacidad': form.get('capacidad', type=int),
    }
    if not campos['nombre'] or len(campos['nombre']) > 100:
        return None, 'Error: El nombre es obligatorio, con máximo 100 caracteres'
    if len(campos['ubicacion']) > 45 or len(campos['dotacion']) > 255:
        return None, 'Error: La ubicación admite 45 caracteres y la dotación 255'
    if campos['capacidad'] is None or not CAPACIDAD_MINIMA <= campos['capacidad'] <= CAPACIDAD_MAXIMA:
        return None, 'Error: La capacidad debe estar entre 1 y 500'
    return campos, None

def notify_affected_reservations(inst):
    hoy = hora_actual().date()
    afectadas = Reserva.query.filter(
        Reserva.instalacion_id == inst.id,
        Reserva.estado == 'activa',
        Reserva.fecha_reserva >= hoy
    ).all()
    estado = inst.estado.replace('_', ' ')
    for reserva in afectadas:
        notificar(reserva.usuario, f'La instalación pasó a {estado}; afecta tu reserva: {describir_reserva(reserva)}.')

def render_espacios(status=200):
    todas = Instalacion.query.filter(Instalacion.estado != 'baja').all()
    return render_template('admin_instalaciones.html', instalaciones=todas, admin_name=session.get('name')), status

@bp.route('/admin_instalaciones')
def admin_instalaciones():
    if session.get('role') != 'admin': return deny_page()
    return render_espacios()

@bp.route('/crear_instalacion', methods=['POST'])
def crear_instalacion():
    if session.get('role') != 'admin': return deny_page()
    
    campos, error = read_space_fields(request.form)
    if error:
        flash(error, 'error')
        return redirect(url_for('instalaciones.admin_instalaciones'))

    descripcion = request.form.get('descripcion')
    file = request.files.get('imagen')
    
    filename = None
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
    
    espacio = Instalacion(descripcion=descripcion, imagen=filename, **campos)
    db.session.add(espacio)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(MENSAJE_NOMBRE_REPETIDO, 'error')
        return redirect(url_for('instalaciones.admin_instalaciones'))
    log_security_event('SPACE_CREATED', details=f'Espacio: {espacio.id}', ip=request.remote_addr)
    flash('Instalación creada con éxito', 'success')
    return redirect(url_for('instalaciones.admin_instalaciones'))

@bp.route('/editar_instalacion/<int:id>', methods=['POST'])
def editar_instalacion(id):
    if session.get('role') != 'admin': return deny_page()
    inst = Instalacion.query.get_or_404(id)
    
    estado = request.form.get('estado')
    roles_permitidos, error = read_roles(request.form)
    campos, error_campos = read_space_fields(request.form)
    error = error or error_campos
    if estado not in ESTADOS_OPERATIVOS:
        error = 'Error: Estado inválido'
    if error:
        flash(error, 'error')
        return redirect(url_for('instalaciones.admin_instalaciones'))

    deja_de_operar = inst.estado == 'activo' and estado != 'activo'
    for campo, valor in campos.items():
        setattr(inst, campo, valor)
    inst.descripcion = request.form.get('descripcion')
    inst.estado = estado
    inst.roles_permitidos = roles_permitidos
    
    file = request.files.get('imagen')
    if file and allowed_file(file.filename):
        # Eliminar imagen anterior si existe
        if inst.imagen:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], inst.imagen)
            if os.path.exists(old_path): os.remove(old_path)
            
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        inst.imagen = filename

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(MENSAJE_NOMBRE_REPETIDO, 'error')
        return redirect(url_for('instalaciones.admin_instalaciones'))
    log_security_event('SPACE_UPDATED', details=f'Espacio: {id}; estado: {inst.estado}', ip=request.remote_addr)
    if deja_de_operar:
        notify_affected_reservations(inst)
    flash('Instalación actualizada', 'success')
    return redirect(url_for('instalaciones.admin_instalaciones'))

@bp.route('/eliminar_instalacion/<int:id>', methods=['POST'])
def eliminar_instalacion(id):
    if session.get('role') != 'admin': return deny_page()
    
    inst = Instalacion.query.get_or_404(id)

    try:
        hoy = hora_actual().date()
        reservas_futuras = Reserva.query.filter(
            Reserva.instalacion_id == id,
            Reserva.estado == 'activa',
            Reserva.fecha_reserva >= hoy
        ).count()
        if reservas_futuras:
            detalle = '1 reserva activa' if reservas_futuras == 1 else f'{reservas_futuras} reservas activas'
            flash(f'El espacio tiene {detalle}', 'error')
            return render_espacios(409)

        if Dispositivo.query.filter_by(instalacion_id=id, estado='activo').count():
            flash('El espacio tiene un lector activo: revócalo antes de darlo de baja', 'error')
            return render_espacios(409)

        inst.estado = 'baja'
        db.session.commit()
        log_security_event('SPACE_RETIRED', details=f'Espacio: {id}', ip=request.remote_addr)
        flash('Instalación eliminada correctamente', 'success')

    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error al eliminar la instalación %s', id)
        flash('Error al eliminar la instalación', 'error')

    return redirect(url_for('instalaciones.admin_instalaciones'))
