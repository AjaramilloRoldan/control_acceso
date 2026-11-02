import pytest

from test_security import client, login_as  # noqa: F401
from app import app
from control_acceso import security
from control_acceso.extensions import db
from control_acceso.models import Admin, Reserva
from crear_admin import crear_admin

CONTRASENA = 'Clave-Segura-123'


def test_admin_is_created_with_bcrypt_hash(client):
    with app.app_context():
        assert crear_admin('directora', CONTRASENA) is None
        creado = Admin.query.filter_by(username='directora').one()

        assert creado.password.startswith('$2b$12$') and security.verify_password(CONTRASENA, creado.password)


def test_admin_username_cannot_repeat(client):
    with app.app_context():
        crear_admin('directora', CONTRASENA)

        assert 'Ya existe' in crear_admin('directora', CONTRASENA)
        assert Admin.query.count() == 1


@pytest.mark.parametrize('username, password', [('a', CONTRASENA), ('directora', 'corta')])
def test_invalid_admin_is_rejected(client, username, password):
    with app.app_context():
        assert crear_admin(username, password) is not None
        assert Admin.query.count() == 0


@pytest.mark.parametrize('pagina', ['abc', '0', '-1', '9999999'])
def test_invalid_user_page_answers_400(client, pagina):
    login_as(client, 'admin', 1)

    assert client.get(f'/usuarios?pagina={pagina}').status_code == 400


def test_valid_user_page_answers_200(client):
    login_as(client, 'admin', 1)

    assert client.get('/usuarios?pagina=2').status_code == 200


@pytest.mark.parametrize('ruta', ['/reservas/1', '/cancelar_reserva/1', '/reservas/999', '/cancelar_reserva/999'])
def test_reservation_changes_without_session_answer_401(client, ruta):
    assert client.post(ruta).status_code == 401


def test_foreign_reservation_answers_403_and_security_event(client, monkeypatch):
    eventos = []
    monkeypatch.setattr(security.security_logger, 'info', eventos.append)
    login_as(client, 'user', 11)

    assert client.post('/cancelar_reserva/1').status_code == 403
    assert any(e.startswith('ACCESS_DENIED') and '/cancelar_reserva/1' in e for e in eventos)
    with app.app_context():
        assert db.session.get(Reserva, 1).estado == 'activa'
