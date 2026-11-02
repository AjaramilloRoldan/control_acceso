from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..clock import hora_actual
from ..extensions import db
from ..models import MOTIVOS_REVOCACION, ROLES_USUARIO, VERSION_AVISO, Reserva, Tarjeta, User
from ..permisos import deny_page
from ..reports import FILAS_POR_PAGINA
from ..security import hash_password, log_security_event
from ..validators import (normalize_uid, read_personal_data, validate_name, validate_password, validate_rfid,
                          validate_username)

bp = Blueprint('usuarios', __name__)

ENDPOINTS_SIN_AVISO = ('usuarios.autorizacion', 'auth.logout', 'static')
FILTROS_ESTADO = ('activo', 'inactivo', 'todos')
MENSAJE_CONTRASENA = 'Error: Contraseña inválida (mínimo 12 caracteres, con mayúsculas, minúsculas, dígitos y símbolos)'
MENSAJE_USUARIO_INACTIVO = 'Error: No se puede asociar una tarjeta a un usuario inactivo'

def revoke_card(tarjeta, motivo):
    tarjeta.estado = 'revocada'
    tarjeta.motivo_revocacion = motivo
    tarjeta.fecha_revocacion = hora_actual()

def replace_active_card(usuario, uid):
    actual = usuario.tarjeta_activa
    if actual and actual.uid == uid:
        return
    if actual:
        revoke_card(actual, 'reemplazo')
    usuario.tarjetas.append(Tarjeta(uid=uid))

def rejects_new_card(usuario, uid):
    actual = usuario.tarjeta_activa
    return bool(uid) and usuario.estado != 'activo' and not (actual and actual.uid == uid)

@bp.before_app_request
def require_privacy_notice():
    if session.get('aviso_pendiente') and request.endpoint not in ENDPOINTS_SIN_AVISO:
        return redirect(url_for('usuarios.autorizacion'))

@bp.route('/autorizacion', methods=['GET', 'POST'])
def autorizacion():
    if session.get('role') != 'user': return deny_page()
    usuario = db.session.get(User, session['user_id'])

    if request.method == 'GET':
        return render_template('autorizacion.html', version_aviso=VERSION_AVISO)

    if request.form.get('decision') == 'rechazar':
        usuario.autorizacion_datos = None
        usuario.version_aviso = None
        db.session.commit()
        log_security_event('PRIVACY_NOTICE_REJECTED', user_id=usuario.id, ip=request.remote_addr)
        session.clear()
        flash('Sin tu autorización no puedes usar la plataforma ni tu tarjeta. El administrador verá tu registro como pendiente.', 'error')
        return redirect(url_for('auth.login'))

    if request.form.get('acepto') != 'on':
        flash('Debes marcar la casilla para aceptar el aviso de privacidad', 'error')
        return redirect(url_for('usuarios.autorizacion'))

    usuario.autorizacion_datos = hora_actual()
    usuario.version_aviso = VERSION_AVISO
    db.session.commit()
    session.pop('aviso_pendiente', None)
    log_security_event('PRIVACY_NOTICE_ACCEPTED', user_id=usuario.id, details=f'Versión: {VERSION_AVISO}', ip=request.remote_addr)
    return redirect(url_for('reservas.instalaciones'))

@bp.route('/usuarios')
def usuarios():
    if session.get('role') != 'admin': return deny_page()
    busqueda = request.args.get('q', '').strip()
    rol = request.args.get('rol', '')
    estado = request.args.get('estado', 'activo')
    status = 200
    if (rol and rol not in ROLES_USUARIO) or estado not in FILTROS_ESTADO:
        flash('Error: Filtro inválido', 'error')
        rol, estado, status = '', 'activo', 400

    consulta = User.query
    if busqueda:
        consulta = consulta.filter(or_(*(campo.contains(busqueda, autoescape=True) for campo in
                                         (User.name, User.apellido, User.identificacion, User.email))))
    if rol:
        consulta = consulta.filter(User.rol == rol)
    if estado != 'todos':
        consulta = consulta.filter(User.estado == estado)

    paginacion = consulta.order_by(User.name, User.id).paginate(
        page=request.args.get('pagina', 1, type=int), per_page=FILAS_POR_PAGINA, error_out=False)
    return render_template('usuarios.html', usuarios=paginacion.items, paginacion=paginacion, roles=ROLES_USUARIO,
                           filtros={'q': busqueda, 'rol': rol, 'estado': estado}), status

@bp.route('/agregar_usuario', methods=['GET', 'POST'])
def agregar_usuario():
    if session.get('role') != 'admin': return deny_page()

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

    if not all([name, username, password]):
        flash('Error: Nombre, usuario y contraseña son obligatorios', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_name(name):
        flash('Error: Nombre inválido (mínimo 2 caracteres, máximo 100)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if rfid and not validate_rfid(rfid):
        flash('Error: RFID inválido (hexadecimal, de 8 a 20 caracteres)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_username(username):
        flash('Error: Usuario inválido (solo alfanuméricos y guiones bajos, 3-50 caracteres)', 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    if not validate_password(password):
        flash(MENSAJE_CONTRASENA, 'error')
        return redirect(url_for('usuarios.usuarios'))
    
    try:
        hashed_password = hash_password(password)
        nuevo = User(name=name, username=username, password=hashed_password, **datos_personales)
        if rfid:
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
    if session.get('role') != 'admin': return deny_page()
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
        
        if (rfid or usuario.tarjeta_activa) and not validate_rfid(rfid):
            flash('Error: RFID inválido (hexadecimal, de 8 a 20 caracteres)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        if not validate_username(username):
            flash('Error: Usuario inválido (solo alfanuméricos y guiones bajos, 3-50 caracteres)', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        if password and not validate_password(password):
            flash(MENSAJE_CONTRASENA, 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))

        if rejects_new_card(usuario, rfid):
            flash(MENSAJE_USUARIO_INACTIVO, 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        
        usuario.name = name
        usuario.username = username
        for campo, valor in datos_personales.items():
            setattr(usuario, campo, valor)
        if rfid:
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
            
    return render_template('editar_usuario.html', usuario=usuario, motivos_revocacion=MOTIVOS_REVOCACION)

@bp.route('/usuarios/<int:id>/tarjeta/eliminar', methods=['POST'])
def revocar_tarjeta(id):
    if session.get('role') != 'admin': return deny_page()
    usuario = User.query.get_or_404(id)
    tarjeta = usuario.tarjeta_activa
    if tarjeta is None:
        abort(404)

    motivo = request.form.get('motivo')
    nuevo_uid = normalize_uid(request.form.get('nuevo_uid', ''))
    client_ip = request.remote_addr
    if motivo not in MOTIVOS_REVOCACION:
        flash('Error: Selecciona el motivo de la revocación', 'error')
        return redirect(url_for('usuarios.editar_usuario', id=id))
    if nuevo_uid and not validate_rfid(nuevo_uid):
        flash('Error: RFID inválido (hexadecimal, de 8 a 20 caracteres)', 'error')
        return redirect(url_for('usuarios.editar_usuario', id=id))
    if nuevo_uid and usuario.estado != 'activo':
        flash(MENSAJE_USUARIO_INACTIVO, 'error')
        return redirect(url_for('usuarios.editar_usuario', id=id))

    revoke_card(tarjeta, motivo)
    db.session.commit()
    log_security_event('CARD_REVOKED', user_id=id, details=f'UID: {tarjeta.uid}; motivo: {motivo}', ip=client_ip)

    if nuevo_uid:
        usuario.tarjetas.append(Tarjeta(uid=nuevo_uid))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('La tarjeta quedó revocada, pero el nuevo RFID ya está asociado a otra tarjeta', 'error')
            return redirect(url_for('usuarios.editar_usuario', id=id))
        log_security_event('CARD_ASSIGNED', user_id=id, details=f'UID: {nuevo_uid}', ip=client_ip)

    flash('Tarjeta revocada correctamente', 'success')
    return redirect(url_for('usuarios.editar_usuario', id=id))

# --- Eliminar Usuario ---

@bp.route('/eliminar_usuario/<int:id>', methods=['POST'])
def eliminar_usuario(id):
    if session.get('role') != 'admin': return deny_page()
    usuario_objeto = User.query.get_or_404(id) 
    
    try:
        hoy = hora_actual().date()
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
