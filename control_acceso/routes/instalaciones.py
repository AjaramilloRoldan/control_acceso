import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Instalacion, Reserva

bp = Blueprint('instalaciones', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/admin_instalaciones')
def admin_instalaciones():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    todas = Instalacion.query.filter(Instalacion.estado != 'baja').all()
    return render_template('admin_instalaciones.html', instalaciones=todas, admin_name=session.get('name'))

@bp.route('/crear_instalacion', methods=['POST'])
def crear_instalacion():
    if session.get('role') != 'admin': return jsonify({"error": "No autorizado"}), 403
    
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')
    file = request.files.get('imagen')
    
    filename = None
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
    
    nueva = Instalacion(nombre=nombre, descripcion=descripcion, imagen=filename)
    db.session.add(nueva)
    db.session.commit()
    flash('Instalación creada con éxito', 'success')
    return redirect(url_for('instalaciones.admin_instalaciones'))

@bp.route('/editar_instalacion/<int:id>', methods=['POST'])
def editar_instalacion(id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    inst = Instalacion.query.get_or_404(id)
    
    inst.nombre = request.form.get('nombre')
    inst.descripcion = request.form.get('descripcion')
    
    file = request.files.get('imagen')
    if file and allowed_file(file.filename):
        # Eliminar imagen anterior si existe
        if inst.imagen:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], inst.imagen)
            if os.path.exists(old_path): os.remove(old_path)
            
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
        inst.imagen = filename
        
    db.session.commit()
    flash('Instalación actualizada', 'success')
    return redirect(url_for('instalaciones.admin_instalaciones'))

@bp.route('/eliminar_instalacion/<int:id>', methods=['POST'])
def eliminar_instalacion(id):
    if session.get('role') != 'admin': 
        return redirect(url_for('auth.login'))
    
    inst = Instalacion.query.get_or_404(id)

    try:
        hoy = datetime.now(ZoneInfo('America/Bogota')).date()
        reservas_futuras = Reserva.query.filter(
            Reserva.instalacion_id == id,
            Reserva.estado == 'activa',
            Reserva.fecha_reserva >= hoy
        ).count()
        if reservas_futuras:
            flash(f'La instalación tiene {reservas_futuras} reserva(s) activa(s)', 'error')
            return redirect(url_for('instalaciones.admin_instalaciones'))

        inst.estado = 'baja'
        db.session.commit()
        flash('Instalación eliminada correctamente', 'success')

    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error al eliminar la instalación %s', id)
        flash('Error al eliminar la instalación', 'error')

    return redirect(url_for('instalaciones.admin_instalaciones'))
