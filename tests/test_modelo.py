from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError

from test_security import DEVICE_HEADERS, client, login_as, reservation_state  # noqa: F401
from app import (AccessLog, Dispositivo, Instalacion, Reserva, Tarjeta, User, app, db, evaluate_access,
                 hash_device_token, hash_password, normalize_uid, validate_rfid)

MIERCOLES = datetime(2026, 11, 4, 10, 0)


def reader_request(client, uid='aabbccdd'):
    return client.post('/historial', json={'uid': uid, 'instalacion_id': 1}, headers=DEVICE_HEADERS)


def change(model, record_id, **fields):
    with app.app_context():
        record = db.session.get(model, record_id)
        for field, value in fields.items():
            setattr(record, field, value)
        db.session.commit()


def book(user_id, inicio, fin, fecha=MIERCOLES.date()):
    with app.app_context():
        db.session.add(Reserva(user_id=user_id, instalacion_id=1, fecha_reserva=fecha, hora_inicio=inicio, hora_fin=fin))
        db.session.commit()


def denial_at(momento, uid='ddeeff00'):
    with app.app_context():
        return evaluate_access(uid, db.session.get(Instalacion, 1), momento)[1]


def new_user_form(**overrides):
    return {'name': 'Eva', 'apellido': 'Mora', 'identificacion': '1088123456', 'email': 'Eva@UCP.edu.co',
            'rol': 'docente', 'rfid': 'A1:B2:C3:D4', 'username': 'eva', 'password': 'clave123', **overrides}


def test_uid_is_normalized_to_lowercase_hex():
    assert normalize_uid('AA:BB cc-DD') == 'aabbccdd'
    assert validate_rfid('aabbccdd') and not validate_rfid('zzbbccdd') and not validate_rfid('aabbcc')


@pytest.mark.parametrize('prepare, uid, motivo', [
    (lambda: None, '12345678', 'TARJETA_NO_REGISTRADA'),
    (lambda: change(Tarjeta, 1, estado='revocada'), 'aabbccdd', 'TARJETA_REVOCADA'),
    (lambda: change(User, 10, estado='inactivo'), 'aabbccdd', 'USUARIO_INACTIVO'),
    (lambda: change(Instalacion, 1, estado='mantenimiento'), 'aabbccdd', 'ESPACIO_NO_OPERATIVO'),
    (lambda: change(Instalacion, 1, roles_permitidos='docente'), 'aabbccdd', 'ROL_NO_AUTORIZADO'),
    (lambda: None, 'ddeeff00', 'SIN_RESERVA_VIGENTE'),
])
def test_denial_reason_is_returned_and_logged(client, prepare, uid, motivo):
    prepare()
    response = reader_request(client, uid)
    body = response.get_json()
    assert response.status_code == 403
    assert body['access'] is False and body['motivo'] == motivo
    with app.app_context():
        log = db.session.get(AccessLog, body['log_id'])
        assert log.motivo == motivo and log.success is False and log.dispositivo_id == 1


def test_authorized_access_has_no_reason(client):
    body = reader_request(client).get_json()
    assert body['access'] is True and body['motivo'] is None


def test_uid_from_reader_is_normalized(client):
    assert reader_request(client, 'AA:BB:CC:DD').status_code == 200


@pytest.mark.parametrize('inicio, fin, autorizado', [
    (time(10, 5), time(11, 0), True),
    (time(10, 10), time(11, 0), True),
    (time(10, 11), time(11, 0), False),
    (time(9, 0), time(10, 0), False),
])
def test_access_margin_before_reservation(client, inicio, fin, autorizado):
    book(11, inicio, fin)
    assert (denial_at(MIERCOLES) is None) is autorizado


def test_margin_does_not_wrap_past_midnight(client):
    book(11, time(23, 58), time(23, 59, 59))
    assert denial_at(MIERCOLES.replace(hour=23, minute=55)) is None


def test_reader_of_other_installation_is_rejected(client):
    with app.app_context():
        db.session.add(Instalacion(id=2, nombre='Sala'))
        db.session.add(Dispositivo(id=2, instalacion_id=2, token_hash=hash_device_token('otro-token')))
        db.session.commit()
    headers = {'X-Device-Token': 'otro-token'}
    response = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=headers)
    assert response.status_code == 403
    with app.app_context():
        assert AccessLog.query.count() == 0


def test_disabled_reader_is_not_authenticated(client):
    change(Dispositivo, 1, estado='inactivo')
    assert reader_request(client).status_code == 401


def test_reader_connection_is_recorded(client):
    reader_request(client)
    with app.app_context():
        assert db.session.get(Dispositivo, 1).ultima_conexion is not None


def test_reader_cannot_report_metrics_of_other_reader(client):
    log_id = reader_request(client).get_json()['log_id']
    with app.app_context():
        db.session.add(Dispositivo(id=2, instalacion_id=1, token_hash=hash_device_token('otro-token')))
        db.session.commit()
    body = {'log_id': log_id, 'tiempo_lectura': 10}
    assert client.post('/api/metricas_acceso', json=body, headers={'X-Device-Token': 'otro-token'}).status_code == 404


def test_storage_failure_denies_access(client, monkeypatch):
    def failing_commit():
        raise SQLAlchemyError('sin conexión')
    monkeypatch.setattr(db.session, 'commit', failing_commit)
    response = reader_request(client)
    assert response.status_code == 500
    assert response.get_json() == {'message': 'Acceso denegado', 'access': False, 'motivo': 'ERROR_REGISTRO'}


def test_admin_registers_user_with_active_card(client):
    login_as(client, 'admin', 1)
    client.post('/agregar_usuario', data=new_user_form())
    with app.app_context():
        user = User.query.filter_by(username='eva').one()
        assert user.email == 'eva@ucp.edu.co' and user.rol == 'docente' and user.rfid == 'a1b2c3d4'


@pytest.mark.parametrize('overrides', [
    {'apellido': ''}, {'identificacion': '12'}, {'email': 'no-es-correo'}, {'rol': 'admin'}, {'rfid': 'xyz'},
])
def test_invalid_registration_is_rejected(client, overrides):
    login_as(client, 'admin', 1)
    client.post('/agregar_usuario', data=new_user_form(**overrides))
    with app.app_context():
        assert User.query.filter_by(username='eva').count() == 0


def test_duplicate_email_is_rejected(client):
    login_as(client, 'admin', 1)
    client.post('/agregar_usuario', data=new_user_form(email='ana@ucp.edu.co'))
    with app.app_context():
        assert User.query.filter_by(username='eva').count() == 0


def test_changing_card_revokes_previous_one(client):
    login_as(client, 'admin', 1)
    client.post('/editar_usuario/10', data={'name': 'Ana', 'rfid': '11223344', 'username': 'ana', 'rol': 'estudiante'})
    with app.app_context():
        anterior = Tarjeta.query.filter_by(uid='aabbccdd').one()
        assert anterior.estado == 'revocada' and anterior.motivo_revocacion == 'reemplazo'
        assert anterior.fecha_revocacion is not None
        assert db.session.get(User, 10).rfid == '11223344'
    assert reader_request(client).get_json()['motivo'] == 'TARJETA_REVOCADA'


def test_editing_without_new_card_keeps_it(client):
    login_as(client, 'admin', 1)
    client.post('/editar_usuario/10', data={'name': 'Ana Mora', 'rfid': 'aabbccdd', 'username': 'ana', 'rol': 'docente'})
    with app.app_context():
        assert Tarjeta.query.filter_by(user_id=10).count() == 1
        assert db.session.get(User, 10).rol == 'docente'


def test_deactivating_user_keeps_log_and_cancels_future_reservations(client):
    reader_request(client)
    login_as(client, 'admin', 1)
    client.post('/eliminar_usuario/10')
    assert reservation_state(1) == 'cancelada'
    with app.app_context():
        assert AccessLog.query.filter_by(user_id=10).count() == 1
        assert db.session.get(User, 10).estado == 'inactivo'


def test_user_logs_in_with_email_or_username(client):
    for identifier in ('ana', 'ana@ucp.edu.co'):
        response = client.post('/login', data={'username': identifier, 'password': 'clave123'})
        assert response.status_code == 302


def test_inactive_user_cannot_log_in(client):
    change(User, 10, estado='inactivo')
    assert client.post('/login', data={'username': 'ana', 'password': 'clave123'}).status_code == 200


def test_installation_with_active_reservations_is_kept(client):
    login_as(client, 'admin', 1)
    client.post('/eliminar_instalacion/1')
    with app.app_context():
        assert db.session.get(Instalacion, 1).estado == 'activo'


def test_installation_without_reservations_is_retired_not_deleted(client):
    change(Reserva, 1, estado='cancelada')
    login_as(client, 'admin', 1)
    client.post('/eliminar_instalacion/1')
    with app.app_context():
        assert db.session.get(Instalacion, 1).estado == 'baja'


def test_retired_installation_rejects_new_reservations(client):
    change(Instalacion, 1, estado='mantenimiento')
    login_as(client, 'user', 11)
    manana = (datetime.now() + timedelta(days=1)).date().isoformat()
    response = client.post('/reservar', data={'instalacion_id': 1, 'fecha': manana, 'hora_inicio': '10:00', 'hora_fin': '11:00'})
    assert response.status_code == 400
