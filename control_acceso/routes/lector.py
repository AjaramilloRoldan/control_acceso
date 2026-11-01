import mysql.connector
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from .. import database
from ..clock import hora_actual
from ..access import evaluate_access
from ..extensions import csrf, db, limiter
from ..metrics import TIEMPO_LECTURA_MAXIMO_MS
from ..models import AccessLog, Dispositivo, Instalacion
from ..security import hash_device_token, log_security_event
from ..validators import normalize_uid, validate_rfid

bp = Blueprint('lector', __name__)

def authenticated_device():
    token_hash = hash_device_token(request.headers.get('X-Device-Token', ''))
    return Dispositivo.query.filter_by(token_hash=token_hash, estado='activo').first()

@bp.route('/historial', methods=['POST'])
@csrf.exempt
@limiter.exempt
def validar_acceso():
    dispositivo = authenticated_device()
    if dispositivo is None:
        log_security_event('DISPOSITIVO_NO_AUTENTICADO', ip=request.remote_addr)
        return jsonify({"message": "Dispositivo no autorizado", "access": False}), 401

    data = request.get_json(silent=True) or {}
    if data.get('instalacion_id') != dispositivo.instalacion_id:
        log_security_event('DEVICE_INSTALLATION_MISMATCH', details=f'Dispositivo: {dispositivo.id}', ip=request.remote_addr)
        return jsonify({"message": "Instalación no asociada al dispositivo", "access": False}), 403

    uid = data.get('uid')
    uid = normalize_uid(uid) if isinstance(uid, str) else ''
    if not validate_rfid(uid):
        return jsonify({"message": "UID inválido", "access": False}), 400

    tiempo_reconexion_wifi = data.get('tiempo_reconexion_wifi')
    if not isinstance(tiempo_reconexion_wifi, int) or tiempo_reconexion_wifi < 0:
        tiempo_reconexion_wifi = None

    ahora = hora_actual()

    try:
        instalacion = db.session.get(Instalacion, dispositivo.instalacion_id)
        user, motivo = evaluate_access(uid, instalacion, ahora)
        registro = AccessLog(user_id=user.id if user else None, rfid_uid=uid, instalacion_id=instalacion.id,
                             dispositivo_id=dispositivo.id, success=motivo is None, motivo=motivo,
                             tiempo_reconexion_wifi=tiempo_reconexion_wifi, timestamp=ahora)
        db.session.add(registro)
        dispositivo.ultima_conexion = ahora
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Error al registrar el acceso del UID %s', uid)
        return jsonify({"message": "Acceso denegado", "access": False, "motivo": "ERROR_REGISTRO"}), 500

    if motivo is None:
        return jsonify({"message": f"Acceso autorizado: {user.name}", "access": True, "motivo": None, "log_id": registro.id}), 200
    return jsonify({"message": "Acceso denegado", "access": False, "motivo": motivo, "log_id": registro.id}), 403

@bp.route('/api/metricas_acceso', methods=['POST'])
@csrf.exempt
@limiter.exempt
def registrar_metricas_acceso():
    dispositivo = authenticated_device()
    if dispositivo is None:
        log_security_event('DISPOSITIVO_NO_AUTENTICADO', ip=request.remote_addr)
        return jsonify({"error": "Dispositivo no autorizado"}), 401

    data = request.get_json(silent=True) or {}
    log_id = data.get('log_id')
    tiempo_lectura = data.get('tiempo_lectura')
    if not isinstance(log_id, int) or not isinstance(tiempo_lectura, int) \
            or not 0 <= tiempo_lectura <= TIEMPO_LECTURA_MAXIMO_MS:
        return jsonify({"error": "Métrica inválida"}), 400

    registro = db.session.get(AccessLog, log_id)
    if registro is None or registro.dispositivo_id != dispositivo.id:
        return jsonify({"error": "Registro no encontrado"}), 404
    if registro.tiempo_lectura_ms is None:
        registro.tiempo_lectura_ms = tiempo_lectura
        db.session.commit()
    return jsonify({"ok": True})

@bp.route('/health')
@limiter.exempt
def health():
    try:
        conn = database.get_db()
        conn.close()
        return jsonify({"status": "ok"})
    except mysql.connector.Error:
        current_app.logger.exception('Fallo de conexión a la base de datos en /health')
        return jsonify({"status": "error"}), 503
