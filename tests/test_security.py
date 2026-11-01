import os
import tempfile
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

os.environ['SECRET_KEY'] = 'test-secret'
os.environ['DATABASE_URL'] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

from app import app
from control_acceso import config, database
from control_acceso.extensions import db, limiter
from control_acceso.models import AccessLog, Dispositivo, Instalacion, Reserva, Tarjeta, User
from control_acceso.security import hash_device_token, hash_password, verify_password

ADMIN_PASSWORD = 'clave-admin-segura'
DEVICE_TOKEN = 'test-device-token'
DEVICE_HEADERS = {'X-Device-Token': DEVICE_TOKEN}


class FakeCursor:
    def __init__(self, admin_row):
        self.admin_row = admin_row

    def execute(self, query, params=None):
        self.params = params

    def fetchone(self):
        if self.admin_row and self.params == (self.admin_row['username'],):
            return self.admin_row
        return None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, admin_row):
        self.admin_row = admin_row

    def cursor(self, dictionary=False):
        return FakeCursor(self.admin_row)

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    limiter.enabled = False
    admin_row = {'id': 1, 'username': 'admin', 'password': hash_password(ADMIN_PASSWORD)}
    monkeypatch.setattr(database, 'get_db', lambda: FakeConnection(admin_row))
    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add(User(id=10, name='Ana', username='ana', email='ana@ucp.edu.co', password=hash_password('clave123')))
        db.session.add(User(id=11, name='Luis', username='luis', password=hash_password('clave123')))
        db.session.add(Instalacion(id=1, nombre='Squash'))
        db.session.add(Dispositivo(id=1, instalacion_id=1, token_hash=hash_device_token(DEVICE_TOKEN)))
        db.session.add(Tarjeta(uid='aabbccdd', user_id=10))
        db.session.add(Tarjeta(uid='ddeeff00', user_id=11))
        ahora = datetime.now(ZoneInfo('America/Bogota'))
        db.session.add(Reserva(
            id=1, user_id=10, instalacion_id=1, fecha_reserva=ahora.date(),
            hora_inicio=time(0, 0), hora_fin=time(23, 59, 59),
        ))
        db.session.commit()
    with app.test_client() as test_client:
        yield test_client


def login_as(client, role, user_id):
    with client.session_transaction() as flask_session:
        flask_session['role'] = role
        flask_session['user_id'] = user_id


def user_exists(user_id):
    with app.app_context():
        return db.session.get(User, user_id) is not None


def reservation_state(reservation_id):
    with app.app_context():
        return db.session.get(Reserva, reservation_id).estado


def test_plaintext_password_is_rejected():
    assert verify_password('clave123', 'clave123') is False


def test_admin_login_requires_matching_bcrypt_hash(client):
    assert client.post('/login', data={'username': 'admin', 'password': 'incorrecta'}).status_code == 200
    response = client.post('/login', data={'username': 'admin', 'password': ADMIN_PASSWORD})
    assert response.status_code == 302 and response.location.endswith('/dashboard')


def test_anonymous_cannot_delete_user(client):
    client.post('/eliminar_usuario/10')
    assert user_exists(10)


def test_regular_user_cannot_delete_user(client):
    login_as(client, 'user', 11)
    client.post('/eliminar_usuario/10')
    assert user_exists(10)


def test_delete_user_rejects_get_even_for_admin(client):
    login_as(client, 'admin', 1)
    assert client.get('/eliminar_usuario/11').status_code == 405
    assert user_exists(11)


def test_admin_can_delete_user_with_post(client):
    login_as(client, 'admin', 1)
    client.post('/eliminar_usuario/11')
    with app.app_context():
        assert db.session.get(User, 11).estado == 'inactivo'


def test_delete_installation_rejects_get(client):
    login_as(client, 'admin', 1)
    assert client.get('/eliminar_instalacion/1').status_code == 405


def test_cancel_reservation_rejects_get_and_other_users(client):
    login_as(client, 'user', 11)
    assert client.get('/cancelar_reserva/1').status_code == 405
    assert client.post('/cancelar_reserva/1').status_code == 403
    assert reservation_state(1) == 'activa'


def test_owner_can_cancel_reservation(client):
    login_as(client, 'user', 10)
    client.post('/cancelar_reserva/1')
    assert reservation_state(1) == 'cancelada'


@pytest.mark.parametrize('headers', [{}, {'X-Device-Token': 'incorrecto'}])
def test_reader_without_valid_token_cannot_request_access(client, headers):
    response = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=headers)
    assert response.status_code == 401
    assert response.get_json()['access'] is False
    with app.app_context():
        assert AccessLog.query.count() == 0


def test_reader_with_token_is_authorized_during_reservation(client):
    response = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    assert response.status_code == 200
    assert 'Acceso autorizado' in response.get_json()['message']


def test_reader_with_token_is_denied_without_reservation(client):
    response = client.post('/historial', json={'uid': 'ddeeff00', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    assert response.status_code == 403
    assert response.get_json()['access'] is False


@pytest.mark.parametrize('uid', [None, 123, 'x', 'aabbcc'])
def test_reader_rejects_invalid_uid(client, uid):
    response = client.post('/historial', json={'uid': uid, 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    assert response.status_code == 400


def test_availability_requires_session_and_valid_date(client):
    day = (date.today() + timedelta(days=1)).isoformat()
    assert client.get(f'/api/disponibilidad/1/{day}').status_code == 401
    login_as(client, 'user', 11)
    assert client.get('/api/disponibilidad/1/no-es-fecha').status_code == 400
    assert client.get(f'/api/disponibilidad/1/{day}').status_code == 200


def test_login_limit_counts_only_login_attempts(client):
    limiter.enabled = True
    limiter.reset()
    try:
        assert all(client.get('/login').status_code == 200 for _ in range(8))
        statuses = [client.post('/login', data={'username': 'x', 'password': 'y'}).status_code for _ in range(6)]
    finally:
        limiter.enabled = False
    assert statuses == [200] * 5 + [429]


def test_app_refuses_to_start_without_required_secret(monkeypatch):
    monkeypatch.delenv('SECRET_KEY')
    with pytest.raises(RuntimeError):
        config.require_env('SECRET_KEY')
