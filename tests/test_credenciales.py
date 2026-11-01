from datetime import datetime

import pytest

from test_modelo import MIERCOLES, change, reader_request
from test_security import client, login_as  # noqa: F401
from app import app
from control_acceso import access
from control_acceso.extensions import db
from control_acceso.models import VERSION_AVISO, Instalacion, Tarjeta, User


def card(uid):
    with app.app_context():
        return Tarjeta.query.filter_by(uid=uid).one()


def revoke(client, user_id=10, **form):
    return client.post(f'/usuarios/{user_id}/tarjeta/eliminar', data=form)


def login(client, username='ana'):
    return client.post('/login', data={'username': username, 'password': 'clave123'})


@pytest.mark.parametrize('motivo', ['perdida', 'deterioro', 'retiro'])
def test_revocation_records_reason_and_date(client, motivo):
    login_as(client, 'admin', 1)

    revoke(client, motivo=motivo)

    tarjeta = card('aabbccdd')
    assert (tarjeta.estado, tarjeta.motivo_revocacion) == ('revocada', motivo)
    assert tarjeta.fecha_revocacion is not None


def test_revoked_card_is_denied_at_reader(client):
    login_as(client, 'admin', 1)
    revoke(client, motivo='perdida')

    assert reader_request(client).get_json()['motivo'] == 'TARJETA_REVOCADA'


def test_revocation_can_assign_new_card_to_same_user(client):
    login_as(client, 'admin', 1)

    revoke(client, motivo='deterioro', nuevo_uid='11:22:33:44')

    with app.app_context():
        usuario = db.session.get(User, 10)
        assert usuario.rfid == '11223344' and len(usuario.tarjetas) == 2


def test_taken_uid_keeps_revocation_without_new_card(client):
    with app.app_context():
        db.session.add(Tarjeta(uid='99887766', user_id=11))
        db.session.commit()
    login_as(client, 'admin', 1)

    revoke(client, motivo='perdida', nuevo_uid='99887766')

    assert card('aabbccdd').estado == 'revocada'
    with app.app_context():
        assert db.session.get(User, 10).tarjeta_activa is None
    assert card('99887766').user_id == 11


@pytest.mark.parametrize('form', [{'motivo': 'capricho'}, {}, {'motivo': 'perdida', 'nuevo_uid': 'zz'}])
def test_invalid_revocation_changes_nothing(client, form):
    login_as(client, 'admin', 1)

    revoke(client, **form)

    assert card('aabbccdd').estado == 'activa'


def test_revocation_without_active_card_is_not_found(client):
    login_as(client, 'admin', 1)
    revoke(client, motivo='perdida')

    assert revoke(client, motivo='perdida').status_code == 404


def test_revocation_requires_admin(client):
    login_as(client, 'user', 10)

    assert revoke(client, motivo='perdida').status_code == 302
    assert card('aabbccdd').estado == 'activa'


def test_user_without_card_can_be_edited_and_get_a_new_one(client):
    login_as(client, 'admin', 1)
    revoke(client, motivo='perdida')
    assert client.get('/editar_usuario/10').status_code == 200
    formulario = {'name': 'Ana', 'username': 'ana', 'rfid': ''}

    client.post('/editar_usuario/10', data={**formulario, 'password': ''})
    with app.app_context():
        assert db.session.get(User, 10).tarjeta_activa is None

    client.post('/editar_usuario/10', data={**formulario, 'rfid': '55667788'})
    with app.app_context():
        assert db.session.get(User, 10).rfid == '55667788'


def test_reader_denies_user_without_authorization(client):
    change(User, 10, autorizacion_datos=None, version_aviso=None)
    with app.app_context():
        instalacion = db.session.get(Instalacion, 1)
        assert access.evaluate_access('aabbccdd', instalacion, MIERCOLES)[1] == 'SIN_AUTORIZACION_DATOS'


def test_authorization_is_checked_after_user_state(client):
    change(User, 10, autorizacion_datos=None, estado='inactivo')
    with app.app_context():
        instalacion = db.session.get(Instalacion, 1)
        assert access.evaluate_access('aabbccdd', instalacion, MIERCOLES)[1] == 'USUARIO_INACTIVO'


def test_login_without_authorization_blocks_platform_until_accepted(client):
    change(User, 10, autorizacion_datos=None, version_aviso=None)

    assert login(client).headers['Location'].endswith('/autorizacion')
    assert client.get('/mis_reservas').headers['Location'].endswith('/autorizacion')
    assert b'name="acepto"' in client.get('/autorizacion').data
    assert b'checked' not in client.get('/autorizacion').data


def test_accepting_records_date_and_version(client):
    change(User, 10, autorizacion_datos=None, version_aviso=None)
    login(client)

    client.post('/autorizacion', data={'decision': 'aceptar', 'acepto': 'on'})

    with app.app_context():
        usuario = db.session.get(User, 10)
        assert usuario.version_aviso == VERSION_AVISO
        assert isinstance(usuario.autorizacion_datos, datetime)
    assert client.get('/instalaciones').status_code == 200


def test_accepting_requires_the_checkbox(client):
    change(User, 10, autorizacion_datos=None, version_aviso=None)
    login(client)

    client.post('/autorizacion', data={'decision': 'aceptar'})

    with app.app_context():
        assert db.session.get(User, 10).autorizacion_datos is None
    assert client.get('/instalaciones').headers['Location'].endswith('/autorizacion')


def test_rejecting_clears_authorization_and_closes_session(client):
    change(User, 10, version_aviso='0.9')
    login(client)

    assert client.post('/autorizacion', data={'decision': 'rechazar'}).headers['Location'].endswith('/login')

    with app.app_context():
        assert db.session.get(User, 10).autorizacion_datos is None
    with client.session_transaction() as sesion:
        assert 'user_id' not in sesion


def test_new_notice_version_asks_again_without_blocking_reader(client):
    change(User, 10, version_aviso='0.9')

    assert reader_request(client).get_json()['motivo'] != 'SIN_AUTORIZACION_DATOS'
    assert login(client).headers['Location'].endswith('/autorizacion')


def test_current_authorization_goes_straight_to_platform(client):
    assert '/autorizacion' not in login(client).headers['Location']


def test_admin_sees_pending_authorization(client):
    login_as(client, 'admin', 1)
    aviso = 'Autorización de datos pendiente'.encode()
    assert aviso not in client.get('/usuarios').data

    change(User, 11, autorizacion_datos=None)

    assert aviso in client.get('/usuarios').data


def test_user_can_log_out_while_notice_is_pending(client):
    change(User, 10, autorizacion_datos=None, version_aviso=None)
    login(client)

    assert client.get('/logout').headers['Location'] == '/'
