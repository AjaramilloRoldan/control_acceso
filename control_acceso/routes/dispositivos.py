import secrets

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import Dispositivo, Instalacion
from ..security import hash_device_token, log_security_event

bp = Blueprint('dispositivos', __name__)

BYTES_TOKEN = 32
LONGITUD_DESCRIPCION = 100

def render_dispositivos(status=200, **contexto):
    lectores = db.session.query(Dispositivo, Instalacion.nombre) \
        .join(Instalacion, Dispositivo.instalacion_id == Instalacion.id) \
        .order_by(Dispositivo.estado, Instalacion.nombre).all()
    espacios = Instalacion.query.filter(Instalacion.estado != 'baja').order_by(Instalacion.nombre).all()
    return render_template('dispositivos.html', lectores=lectores, espacios=espacios, **contexto), status

@bp.route('/dispositivos', methods=['GET', 'POST'])
def dispositivos():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    if request.method == 'GET':
        return render_dispositivos()

    instalacion_id = request.form.get('id_espacios', type=int)
    instalacion = db.session.get(Instalacion, instalacion_id) if instalacion_id else None
    if instalacion is None:
        abort(404)
    if instalacion.estado == 'baja':
        return render_dispositivos(409, error='El espacio está dado de baja')

    descripcion = request.form.get('descripcion', '').strip()
    if not descripcion or len(descripcion) > LONGITUD_DESCRIPCION:
        return render_dispositivos(400, error='La descripción es obligatoria, con máximo 100 caracteres')

    token = secrets.token_hex(BYTES_TOKEN)
    lector = Dispositivo(instalacion_id=instalacion.id, descripcion=descripcion, token_hash=hash_device_token(token))
    db.session.add(lector)
    db.session.commit()
    log_security_event('DEVICE_REGISTERED', details=f'Dispositivo: {lector.id}', ip=request.remote_addr)

    respuesta = make_response(render_dispositivos(201, token=token, token_instalacion=instalacion.id))
    respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta

@bp.route('/dispositivos/<int:id>/revocar', methods=['POST'])
def revocar_dispositivo(id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    lector = Dispositivo.query.get_or_404(id)
    if lector.estado != 'activo':
        return render_dispositivos(409, error='El lector ya estaba revocado')

    lector.estado = 'revocado'
    db.session.commit()
    log_security_event('DEVICE_REVOKED', details=f'Dispositivo: {id}', ip=request.remote_addr)
    flash('Lector revocado. Su token dejó de funcionar', 'success')
    return redirect(url_for('dispositivos.dispositivos'))
