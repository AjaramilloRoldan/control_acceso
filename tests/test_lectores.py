import re
from datetime import date, datetime, time

import pytest

from test_modelo import change, reader_request
from test_security import DEVICE_TOKEN, client, login_as  # noqa: F401
from app import app
from control_acceso.clock import hora_actual
from control_acceso.extensions import db, limiter
from control_acceso.models import AccessLog, Dispositivo, Instalacion, Reserva
from control_acceso.reports import FILAS_POR_PAGINA
from control_acceso.security import hash_device_token


def new_reader(client, **overrides):
    return client.post('/dispositivos', data={'id_espacios': 1, 'descripcion': 'Puerta norte', **overrides})


def token_in(response):
    return re.search(r'\b[0-9a-f]{64}\b', response.get_data(as_text=True)).group()


def log(momento, success=True, user_id=10, instalacion_id=1, motivo=None):
    with app.app_context():
        db.session.add(AccessLog(user_id=user_id, rfid_uid='aabbccdd', instalacion_id=instalacion_id,
                                 timestamp=momento, success=success, motivo=motivo))
        db.session.commit()


def rows(response):
    return response.get_data(as_text=True).count('class="log-row')


def test_reader_token_is_shown_once_and_stored_hashed(client):
    login_as(client, 'admin', 1)

    response = new_reader(client)

    token = token_in(response)
    assert response.status_code == 201 and len(token) == 64
    assert response.headers['Cache-Control'] == 'no-store'
    with app.app_context():
        assert Dispositivo.query.filter_by(token_hash=hash_device_token(token)).one().descripcion == 'Puerta norte'
    assert token not in client.get('/dispositivos').get_data(as_text=True)


def test_registered_token_authenticates_reader(client):
    login_as(client, 'admin', 1)
    token = token_in(new_reader(client))

    respuesta = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers={'X-Device-Token': token})

    assert respuesta.status_code != 401


def test_revoked_reader_gets_unauthorized(client):
    login_as(client, 'admin', 1)
    with app.app_context():
        lector_id = Dispositivo.query.filter_by(token_hash=hash_device_token(DEVICE_TOKEN)).one().id

    client.post(f'/dispositivos/{lector_id}/revocar')

    assert reader_request(client).status_code == 401
    assert client.post(f'/dispositivos/{lector_id}/revocar').status_code == 409


def test_reader_needs_existing_active_space(client):
    login_as(client, 'admin', 1)

    assert new_reader(client, id_espacios=999).status_code == 404
    change(Instalacion, 1, estado='baja')
    assert new_reader(client).status_code == 409


@pytest.mark.parametrize('descripcion', ['', '   ', 'x' * 101])
def test_reader_needs_valid_description(client, descripcion):
    login_as(client, 'admin', 1)

    assert new_reader(client, descripcion=descripcion).status_code == 400


def test_reader_management_requires_admin(client):
    login_as(client, 'user', 10)

    assert client.get('/dispositivos').status_code == 302
    assert new_reader(client).status_code == 302


def test_log_combines_filters(client):
    login_as(client, 'admin', 1)
    log(datetime(2030, 1, 7, 10, 0), False, motivo='ROL_NO_AUTORIZADO')
    log(datetime(2030, 1, 7, 11, 0), True)
    log(datetime(2030, 1, 8, 10, 0), False, motivo='SIN_RESERVA_VIGENTE')

    response = client.get('/historial?resultado=denegado&id_espacios=1&motivo=ROL_NO_AUTORIZADO')
    assert rows(response) == 1
    assert 'ROL_NO_AUTORIZADO</td>' in response.get_data(as_text=True).replace(' ', '')
    assert rows(client.get('/historial?fecha_desde=2030-01-07&fecha_hasta=2030-01-07')) == 2
    assert rows(client.get('/historial?id_usuario=11')) == 0


def test_log_is_paginated_newest_first(client):
    login_as(client, 'admin', 1)
    for dia in range(1, FILAS_POR_PAGINA + 4):
        log(datetime(2030, 1, dia, 10, 0))

    primera = client.get('/historial').get_data(as_text=True)
    segunda = client.get('/historial?pagina=2')

    assert primera.count('class="log-row') == FILAS_POR_PAGINA
    assert primera.index('2030-01-23') < primera.index('2030-01-22')
    assert rows(segunda) == 3


def test_pagination_links_keep_filters(client):
    login_as(client, 'admin', 1)
    for dia in range(1, FILAS_POR_PAGINA + 2):
        log(datetime(2030, 1, dia, 10, 0), False)

    assert 'resultado=denegado' in client.get('/historial?resultado=denegado').get_data(as_text=True).split('Siguiente')[0][-300:]


@pytest.mark.parametrize('consulta', ['fecha_desde=2030-02-01&fecha_hasta=2030-01-01', 'fecha_desde=ayer'])
def test_log_rejects_invalid_dates(client, consulta):
    login_as(client, 'admin', 1)

    assert client.get(f'/historial?{consulta}').status_code == 400


def test_user_sees_only_own_records(client):
    log(datetime(2030, 1, 7, 10, 0), user_id=10)
    log(datetime(2030, 1, 7, 11, 0), user_id=11)
    login_as(client, 'user', 10)

    assert rows(client.get('/historial')) == 1
    assert rows(client.get('/historial?id_usuario=10')) == 1


def test_user_cannot_filter_by_another_user(client):
    login_as(client, 'user', 10)

    assert client.get('/historial?id_usuario=11').status_code == 403


def test_log_requires_session(client):
    assert client.get('/historial').status_code == 302


def test_monitoring_returns_panel_data(client):
    ahora = hora_actual()
    log(ahora, True)
    log(ahora, False, motivo='SIN_RESERVA_VIGENTE')
    with app.app_context():
        db.session.add(Reserva(user_id=10, instalacion_id=1, fecha_reserva=ahora.date(), hora_inicio=time(8, 0), hora_fin=time(9, 0)))
        db.session.add(Reserva(user_id=10, instalacion_id=1, fecha_reserva=date(2030, 1, 7), hora_inicio=time(8, 0), hora_fin=time(9, 0)))
        db.session.commit()
    reader_request(client)
    login_as(client, 'admin', 1)

    data = client.get('/api/monitoreo').get_json()

    assert data['autorizados_hoy'] + data['denegados_hoy'] == 3
    assert data['ultimos_accesos'][0]['espacio'] == 'Squash'
    franjas = [reserva['franja'] for reserva in data['reservas_hoy']]
    assert '08:00 - 09:00' in franjas and len(franjas) == 2
    assert data['dispositivos'][0]['ultima_conexion'] is not None


def test_monitoring_lists_new_access_immediately(client):
    login_as(client, 'admin', 1)
    assert client.get('/api/monitoreo').get_json()['ultimos_accesos'] == []

    log(hora_actual(), False)

    assert len(client.get('/api/monitoreo').get_json()['ultimos_accesos']) == 1


def test_polling_every_five_seconds_is_not_rate_limited(client):
    login_as(client, 'admin', 1)
    limiter.enabled = True
    try:
        polling = {client.get('/api/monitoreo').status_code for _ in range(60)}
        ruta_normal = {client.get('/dispositivos').status_code for _ in range(60)}
    finally:
        limiter.enabled = False
        limiter.reset()

    assert polling == {200}
    assert 429 in ruta_normal


def test_monitoring_requires_admin(client):
    login_as(client, 'user', 10)

    assert client.get('/api/monitoreo').status_code == 401
