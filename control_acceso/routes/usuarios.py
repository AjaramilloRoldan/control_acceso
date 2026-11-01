from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Reserva, Tarjeta, User
from ..security import hash_password, log_security_event
from ..validators import (normalize_uid, read_personal_data, validate_name, validate_password, validate_rfid,
                          validate_username)

bp = Blueprint('usuarios', __name__)

def replace_active_card(usuario, uid):
    actual = usuario.tarjeta_activa
    if actual and actual.uid == uid:
        return
    if actual:
        actual.estado = 'revocada'
        actual.motivo_revocacion = 'reemplazo'
        actual.fecha_revocacion = datetime.now()
    usuario.tarjetas.append(Tarjeta(uid=uid))

@bp.route('/usuarios')
def usuarios():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    usuarios_lista = User.query.filter_by(estado='activo').all()
    return render_template('usuarios.html', usuarios=usuarios_lista)

@bp.route('/agregar_usuario', methods=['GET', 'POST'])
def agregar_usuario():
    if session.get('role') != 'admin': 
        return redirect(url_for('auth.login'))

    if request.method == 'GET':
        rfid_pre = request.args.get('rfid', '')
        return render_template('agregar_usuario.html', rfid_pre=rfid_pre)

    name = request.form.get('name')
    rfid = normalize_uid(request.form.get('rfid', ''))
    username = request.form.get('username')
    password = request.form.get('password')
    client_ip = request.remote_addr

    # VALIDACIÓN
    datos_personales, error = read_personal_data(request.form, required=True)
    if error:
        flash(error, 'error')
        return redirect(url_for('usuarios.usuarios'))

    if not all([name, rfid, username, password]):
        flash('Error: Todos los campos son obligatorios', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_name(name):
        flash('Error: Nombre inválido (mínimo 2 caracteres, máximo 100)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_rfid(rfid):
        flash('Error: RFID inválido (hexadecimal, de 8 a 20 caracteres)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_username(username):
        flash('Error: Usuario inválido (solo alfanuméricos y guiones bajos, 3-50 caracteres)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_password(password):
        flash('Error: Contraseña inválida (mínimo 6 caracteres)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    try:
        hashed_password = hash_password(password)
        nuevo = User(name=name, username=username, password=hashed_password, **datos_personales)
        nuevo.tarjetas.append(Tarjeta(uid=rfid))
        db.session.add(nuevo)
        db.session.commit()
        log_security_event('USER_CREATED', user_id=nuevo.id, details=f'Username: {username}', ip=client_ip)
        flash('Usuario registrado con éxito', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Error al registrar: El UID, usuario, correo o identificación ya existen', 'error')
        
    return redirect(url_for('usuarios.usuarios'))

@bp.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
def editar_usuario(id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    usuario = User.query.get_or_404(id)
    client_ip = request.remote_addr
    
    if request.method == 'POST':
        name = request.form.get('name')
        rfid = normalize_uid(request.form.get('rfid', ''))
        username = request.form.get('username')
        password = request.form.get('password')

        # VALIDACIÓN
        datos_personales, error = read_personal_data(request.form, required=False)
        if error:
            flash(error, 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))

        if not validate_name(name):
            flash('Error: Nombre inválido (mínimo 2 caracteres, máximo 100)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        if not validate_rfid(rfid):
            flash('Error: RFID inválido (hexadecimal, de 8 a 20 caracteres)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        if not validate_username(username):
            flash('Error: Usuario inválido (solo alfanuméricos y guiones bajos, 3-50 caracteres)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        if password and not validate_password(password):
            flash('Error: Contraseña inválida (mínimo 6 caracteres)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        usuario.name = name
        usuario.username = username
        for campo, valor in datos_personales.items():
            setattr(usuario, campo, valor)
        replace_active_card(usuario, rfid)
        if password:
            usuario.password = hash_password(password)
            
        try:
            db.session.commit()
            log_security_event('USER_UPDATED', user_id=id, details=f'Username: {usuario.username}', ip=client_ip)
            flash('Cambio aplicado correctamente', 'success') 
            return redirect(url_for('usuarios.usuarios')) 
        except IntegrityError:
            db.session.rollback()
            flash('Error: El RFID, usuario, correo o identificación ya existen', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
            
    return render_template('editar_usuario.html', usuario=usuario)

# --- Eliminar Usuario ---

@bp.route('/eliminar_usuario/<int:id>', methods=['POST'])
def eliminar_usuario(id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    usuario_objeto = User.query.get_or_404(id) 
    
    try:
        hoy = datetime.now(ZoneInfo('America/Bogota')).date()
        usuario_objeto.estado = 'inactivo'
        Reserva.query.filter(
            Reserva.user_id == id,
            Reserva.estado == 'activa',
            Reserva.fecha_reserva >= hoy
        ).update({'estado': 'cancelada'})
        db.session.commit()
        log_security_event('USER_DEACTIVATED', user_id=id, ip=request.remote_addr)
        flash('Usuario desactivado exitosamente', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error al desactivar el usuario %s', id)
        flash('Error al desactivar el usuario', 'error') 
        
    return redirect(url_for('usuarios.usuarios'))
