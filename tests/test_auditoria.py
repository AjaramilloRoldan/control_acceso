import time as reloj
from datetime import date, datetime, time

import mysql.connector
import pytest

from test_security import DEVICE_HEADERS, client, login_as  # noqa: F401
from test_modelo import change, new_user_form
from app import app
from control_acceso import config, database, security
from control_acceso.access import evaluate_access
from control_acceso.extensions import db
from control_acceso.models import AccessLog, Dispositivo, Instalacion, Reserva, Tarjeta, User
from control_acceso.validators import validate_password

CONTRASENA_VALIDA = 'Clave-Segura-123'


@pytest.fixture
def eventos(monkeypatch):
    registrados = []
    monkeypatch.setattr(security.security_logger, 'info', registrados.append)
    return registrados


def validate_request(client, **cuerpo):
    return client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1, **cuerpo}, headers=DEVICE_HEADERS)


@pytest.mark.parametrize('username, password', [('ana', 'incorrecta'), ('nadie', 'incorrecta')])
def test_failed_login_answers_generic_401(client, username, password):
    response = client.post('/login', data={'username': username, 'password': password})

    assert response.status_code == 401 and 'Credenciales inválidas' in response.get_data(as_text=True)


def test_inactive_user_gets_same_login_error(client):
    change(User, 10, estado='inactivo')
    response = client.post('/login', data={'username': 'ana', 'password': 'clave123'})

    assert response.status_code == 401 and 'Credenciales inválidas' in response.get_data(as_text=True)


def test_login_answers_503_when_database_is_down(client, monkeypatch):
    def base_caida():
        raise mysql.connector.Error('caida')

    monkeypatch.setattr(database, 'get_db', base_caida)

    assert client.post('/login', data={'username': 'ana', 'password': 'clave123'}).status_code == 503


def test_unauthorized_role_gets_403_and_security_event(client, eventos):
    login_as(client, 'user', 10)

    assert client.get('/usuarios').status_code == 403
    assert any(e.startswith('ACCESS_DENIED') and '/usuarios' in e and 'Rol: user' in e for e in eventos)


def test_admin_keeps_access_to_user_list(client):
    login_as(client, 'admin', 1)

    assert client.get('/usuarios').status_code == 200


def test_missing_session_redirects_pages_and_rejects_json(client):
    assert client.get('/usuarios').headers['Location'].endswith('/login')
    assert client.get('/api/stats').status_code == 401


def test_unauthorized_role_gets_403_on_json_route(client):
    login_as(client, 'user', 10)

    assert client.get('/api/stats').status_code == 403


def test_expired_session_answers_401_on_json_route(client):
    login_as(client, 'admin', 1)
    with client.session_transaction() as sesion:
        sesion['expira_en'] = reloj.time() - 1

    assert client.get('/api/stats').status_code == 401


@pytest.mark.parametrize('query', ['rol=inventado', 'estado=inventado'])
def test_invalid_user_filter_answers_400(client, query):
    login_as(client, 'admin', 1)

    assert client.get(f'/usuarios?{query}').status_code == 400


@pytest.mark.parametrize('query', ['rol=docente', 'estado=inactivo', 'estado=todos', 'q=ana'])
def test_valid_user_filter_answers_200(client, query):
    login_as(client, 'admin', 1)

    assert client.get(f'/usuarios?{query}').status_code == 200


def test_empty_user_search_shows_required_message(client):
    login_as(client, 'admin', 1)

    assert 'No se encontraron usuarios' in client.get('/usuarios?q=zzzzz').get_data(as_text=True)


def inactive_user_without_card():
    with app.app_context():
        usuario = db.session.get(User, 11)
        usuario.estado = 'inactivo'
        usuario.tarjetas[0].estado = 'revocada'
        db.session.commit()


def test_card_is_not_assigned_to_inactive_user(client):
    inactive_user_without_card()
    login_as(client, 'admin', 1)
    formulario = new_user_form(rfid='11223344', username='luis', name='Luis')
    formulario.pop('password')
    client.post('/editar_usuario/11', data=formulario)

    with app.app_context():
        assert Tarjeta.query.filter_by(uid='11223344').first() is None


def test_inactive_user_keeps_editing_with_same_card(client):
    change(User, 10, estado='inactivo')
    login_as(client, 'admin', 1)
    formulario = new_user_form(rfid='aabbccdd', username='ana', name='Ana Maria')
    formulario.pop('password')
    client.post('/editar_usuario/10', data=formulario)

    with app.app_context():
        assert db.session.get(User, 10).name == 'Ana Maria'


def test_replacement_card_is_rejected_for_inactive_user(client):
    change(User, 10, estado='inactivo')
    login_as(client, 'admin', 1)
    client.post('/usuarios/10/tarjeta/eliminar', data={'motivo': 'perdida', 'nuevo_uid': '11223344'})

    with app.app_context():
        assert db.session.get(User, 10).tarjeta_activa.uid == 'aabbccdd'
        assert Tarjeta.query.filter_by(uid='11223344').first() is None


@pytest.mark.parametrize('contrasena, valida', [
    (CONTRASENA_VALIDA, True),
    ('Corta-1', False),
    ('sinmayusculas-123', False),
    ('SINMINUSCULAS-123', False),
    ('Sin-Digitos-Aqui', False),
    ('SinSimbolos12345', False),
])
def test_password_policy(contrasena, valida):
    assert validate_password(contrasena) is valida


def test_user_is_created_without_card(client):
    login_as(client, 'admin', 1)
    formulario = new_user_form(password=CONTRASENA_VALIDA)
    formulario.pop('rfid')
    client.post('/agregar_usuario', data=formulario)

    with app.app_context():
        creado = User.query.filter_by(username=formulario['username']).one()
        assert creado.tarjeta_activa is None


def test_availability_of_unknown_space_answers_404(client):
    login_as(client, 'user', 10)

    assert client.get('/api/disponibilidad/999/2030-01-07').status_code == 404


def test_availability_of_retired_space_answers_404(client):
    change(Instalacion, 1, estado='baja')
    login_as(client, 'user', 10)

    assert client.get('/api/disponibilidad/1/2030-01-07').status_code == 404


def test_retiring_space_with_reservation_answers_409(client):
    login_as(client, 'admin', 1)
    response = client.post('/eliminar_instalacion/1')

    assert response.status_code == 409 and 'El espacio tiene 1 reserva activa' in response.get_data(as_text=True)


def test_retiring_space_with_active_reader_answers_409(client):
    change(Reserva, 1, estado='cancelada')
    login_as(client, 'admin', 1)
    response = client.post('/eliminar_instalacion/1')

    assert response.status_code == 409 and 'lector activo' in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Instalacion, 1).estado == 'activo'


def test_space_is_retired_once_reader_is_revoked(client, eventos):
    change(Reserva, 1, estado='cancelada')
    change(Dispositivo, 1, estado='revocado')
    login_as(client, 'admin', 1)
    client.post('/eliminar_instalacion/1')

    with app.app_context():
        assert db.session.get(Instalacion, 1).estado == 'baja'
    assert any(e.startswith('SPACE_RETIRED') and 'Actor: admin:1' in e for e in eventos)


def test_invalid_uid_is_logged(client):
    response = validate_request(client, uid='no-es-hex')

    assert response.status_code == 400
    with app.app_context():
        registro = AccessLog.query.filter_by(motivo='UID_INVALIDO').one()
        assert registro.success is False and registro.rfid_uid == 'noeshex' and registro.instalacion_id == 1


def test_non_text_uid_is_logged_without_value(client):
    assert validate_request(client, uid=12345).status_code == 400
    with app.app_context():
        assert AccessLog.query.filter_by(motivo='UID_INVALIDO').one().rfid_uid is None


def test_foreign_installation_payload_does_not_override_device_association(client):
    assert validate_request(client, instalacion_id=99).status_code == 200
    with app.app_context():
        registro = AccessLog.query.order_by(AccessLog.id.desc()).first()
        assert registro.success and registro.instalacion_id == 1


def test_space_data_stays_out_of_inline_handlers(client):
    change(Instalacion, 1, nombre="Sala O'Neil", descripcion='Línea uno\nLínea dos')
    login_as(client, 'admin', 1)
    admin = client.get('/admin_instalaciones').get_data(as_text=True)
    assert "onclick=\"openModal('edit', this)\"" in admin and 'data-nombre="Sala O&#39;Neil"' in admin

    login_as(client, 'user', 10)
    usuario = client.get('/instalaciones').get_data(as_text=True)
    assert 'onclick="openBookingModal(this)"' in usuario and 'data-nombre="Sala O&#39;Neil"' in usuario


def test_admin_operations_name_their_actor(client, eventos):
    login_as(client, 'admin', 1)
    client.post('/editar_usuario/10', data={**new_user_form(rfid='aabbccdd', username='ana', name='Ana Maria'), 'password': ''})
    client.post('/crear_instalacion', data={'nombre': 'Sala nueva', 'capacidad': '4'})

    for evento in ('USER_UPDATED', 'SPACE_CREATED'):
        assert any(e.startswith(evento) and 'Actor: admin:1' in e for e in eventos)


def test_security_event_stays_on_one_line(client, eventos):
    client.post('/login', data={'username': 'ana\nLOGIN_SUCCESS', 'password': 'x'})

    assert all('\n' not in evento for evento in eventos)


def test_access_margin_comes_from_configuration(client, monkeypatch):
    with app.app_context():
        db.session.add(Reserva(user_id=10, instalacion_id=1, fecha_reserva=date(2030, 1, 7), hora_inicio=time(10, 0), hora_fin=time(11, 0)))
        db.session.commit()
        momento = datetime(2030, 1, 7, 9, 55)
        espacio = db.session.get(Instalacion, 1)

        assert evaluate_access('aabbccdd', espacio, momento)[1] is None
        monkeypatch.setattr(config, 'MARGEN_ACCESO_MINUTOS', 0)
        assert evaluate_access('aabbccdd', espacio, momento)[1] == 'SIN_RESERVA_VIGENTE'


def test_date_indexes_are_declared():
    nombres = {indice.name for indice in AccessLog.__table__.indexes | Reserva.__table__.indexes}

    assert {'idx_access_log_instalacion_fecha', 'idx_access_log_fecha', 'idx_reservas_instalacion_fecha'} <= nombres
