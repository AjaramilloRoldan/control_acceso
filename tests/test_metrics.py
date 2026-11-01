from datetime import datetime

import pytest

from test_security import DEVICE_HEADERS, client  # noqa: F401
from app import AccessLog, app, calcular_disponibilidad, percentil_95


def stored_log(log_id):
    with app.app_context():
        from app import db
        return db.session.get(AccessLog, log_id)


def validate(client, uid='aabbcc', **extra):
    return client.post('/historial', json={'uid': uid, 'instalacion_id': 1, **extra}, headers=DEVICE_HEADERS)


def test_access_stores_installation_and_ignores_client_read_time(client):
    log_id = validate(client, tiempo_lectura=999).get_json()['log_id']
    log = stored_log(log_id)
    assert log.instalacion_id == 1
    assert log.tiempo_lectura_ms is None


def test_denied_access_also_returns_log_id(client):
    response = validate(client, uid='ddeeff')
    assert stored_log(response.get_json()['log_id']).success is False


@pytest.mark.parametrize('inst_id', [None, 'x', 999])
def test_access_rejects_invalid_installation(client, inst_id):
    response = client.post('/historial', json={'uid': 'aabbcc', 'instalacion_id': inst_id}, headers=DEVICE_HEADERS)
    assert response.status_code == 400


def test_read_time_is_stored_once(client):
    log_id = validate(client).get_json()['log_id']
    body = {'log_id': log_id, 'tiempo_lectura': 180}
    assert client.post('/api/metricas_acceso', json=body, headers=DEVICE_HEADERS).status_code == 200
    client.post('/api/metricas_acceso', json={**body, 'tiempo_lectura': 5}, headers=DEVICE_HEADERS)
    assert stored_log(log_id).tiempo_lectura_ms == 180


def test_read_time_requires_device_token(client):
    log_id = validate(client).get_json()['log_id']
    assert client.post('/api/metricas_acceso', json={'log_id': log_id, 'tiempo_lectura': 1}).status_code == 401


@pytest.mark.parametrize('body, status', [
    ({'log_id': 'x', 'tiempo_lectura': 1}, 400),
    ({'log_id': 1, 'tiempo_lectura': -1}, 400),
    ({'log_id': 1, 'tiempo_lectura': 60001}, 400),
    ({'log_id': 999, 'tiempo_lectura': 1}, 404),
])
def test_read_time_rejects_invalid_values(client, body, status):
    assert client.post('/api/metricas_acceso', json=body, headers=DEVICE_HEADERS).status_code == status


def test_percentile_95_uses_nearest_rank():
    assert percentil_95([]) is None
    assert percentil_95([7]) == 7
    assert percentil_95(list(range(1, 101))) == 95


def test_availability_without_data_is_unknown(tmp_path):
    assert calcular_disponibilidad(tmp_path / 'no-existe.log') is None


def test_availability_counts_only_recent_academic_hours(tmp_path):
    log = tmp_path / 'disponibilidad.log'
    log.write_text(
        '2026-11-02T08:00:00,ok\n'    # lunes, cuenta
        '2026-11-02T08:01:00,ok\n'    # lunes, cuenta
        '2026-11-02T08:02:00,ok\n'    # lunes, cuenta
        '2026-11-02T08:03:00,fallo\n'  # lunes, cuenta
        '2026-11-02T23:00:00,fallo\n'  # fuera de horario
        '2026-11-01T10:00:00,fallo\n'  # domingo
        '2026-09-01T10:00:00,fallo\n'  # más de 30 días
        'linea-rota\n',
        encoding='utf-8',
    )
    assert calcular_disponibilidad(log, ahora=datetime(2026, 11, 3, 12, 0)) == 75.0
