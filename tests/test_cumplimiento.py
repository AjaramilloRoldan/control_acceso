import json
import pathlib
import re
from datetime import date, datetime, time

import pytest

from test_lectores import log
from test_security import DEVICE_HEADERS, client, login_as  # noqa: F401
from app import app
import depurar_bitacora as script_depuracion
from control_acceso import database
from control_acceso.extensions import db
from control_acceso.formatos import fecha_hora_local, fecha_local
from control_acceso.models import AccessLog, Instalacion, Notificacion, Reserva
from control_acceso.notifications import describir_reserva
from control_acceso.reports import reporte_bitacora, to_csv
from control_acceso.retencion import depurar_bitacora, fecha_limite

OPENAPI = json.loads((pathlib.Path(__file__).parent.parent / 'docs' / 'openapi.json').read_text(encoding='utf-8'))
RUTAS_JSON_FUERA_DE_API = {('/historial', 'POST'), ('/health', 'GET'), ('/reservar', 'POST'),
                           ('/reservas/{reserva_id}', 'POST'), ('/cancelar_reserva/{reserva_id}', 'POST')}
TIPOS = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'integer': int, 'number': (int, float)}
FECHA_HORA = re.compile(r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$')


def resolve(nodo):
    while '$ref' in nodo:
        destino = OPENAPI
        for parte in nodo['$ref'].removeprefix('#/').split('/'):
            destino = destino[parte]
        nodo = destino
    return nodo


def check_schema(valor, esquema, ruta='$'):
    esquema = resolve(esquema)
    if valor is None:
        assert esquema.get('nullable'), f'{ruta} no admite null'
        return
    assert isinstance(valor, TIPOS[esquema['type']]), f'{ruta}: {valor!r}'
    if 'enum' in esquema:
        assert valor in esquema['enum']
    if esquema['type'] == 'object':
        for clave in esquema.get('required', []):
            assert clave in valor, f'{ruta}.{clave} ausente'
        for clave, propiedad in valor.items():
            assert clave in esquema['properties'], f'{ruta}.{clave} sin documentar'
            check_schema(propiedad, esquema['properties'][clave], f'{ruta}.{clave}')
    if esquema['type'] == 'array':
        for indice, elemento in enumerate(valor):
            check_schema(elemento, esquema['items'], f'{ruta}[{indice}]')


def check_contract(respuesta, ruta, metodo='post'):
    respuestas = OPENAPI['paths'][ruta][metodo]['responses']
    estado = str(respuesta.status_code)
    documentada = respuestas.get(estado) or respuestas[f'{estado[0]}XX']
    check_schema(respuesta.get_json(), resolve(documentada)['content']['application/json']['schema'])


def plantilla_openapi(regla):
    return re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', regla)


def test_every_json_route_is_documented():
    registradas = {(plantilla_openapi(regla.rule), metodo) for regla in app.url_map.iter_rules()
                   if regla.rule.startswith('/api/') for metodo in regla.methods - {'HEAD', 'OPTIONS'}}
    documentadas = {(ruta, metodo.upper()) for ruta, operaciones in OPENAPI['paths'].items() for metodo in operaciones}

    assert documentadas == registradas | RUTAS_JSON_FUERA_DE_API


def test_documented_routes_exist():
    rutas = {(plantilla_openapi(regla.rule), metodo) for regla in app.url_map.iter_rules() for metodo in regla.methods}

    assert RUTAS_JSON_FUERA_DE_API <= rutas


def test_reader_contract_for_each_decision(client):
    autorizado = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    denegado = client.post('/historial', json={'uid': 'ffffffff', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    invalido = client.post('/historial', json={'uid': 'x', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    sin_token = client.post('/historial', json={})

    assert [r.status_code for r in (autorizado, denegado, invalido, sin_token)] == [200, 403, 400, 401]
    for respuesta in (autorizado, denegado, invalido, sin_token):
        check_contract(respuesta, '/historial')


def test_metrics_contract(client):
    log_id = client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=DEVICE_HEADERS).get_json()['log_id']

    correcta = client.post('/api/metricas_acceso', json={'log_id': log_id, 'tiempo_lectura': 120}, headers=DEVICE_HEADERS)
    ausente = client.post('/api/metricas_acceso', json={'log_id': 999, 'tiempo_lectura': 120}, headers=DEVICE_HEADERS)

    assert (correcta.status_code, ausente.status_code) == (200, 404)
    check_contract(correcta, '/api/metricas_acceso')
    check_contract(ausente, '/api/metricas_acceso')


def test_health_contract(client):
    check_contract(client.get('/health'), '/health', 'get')


def test_monitoring_contract(client):
    client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    login_as(client, 'admin', 1)

    respuesta = client.get('/api/monitoreo')

    check_contract(respuesta, '/api/monitoreo', 'get')
    assert FECHA_HORA.match(respuesta.get_json()['ultimos_accesos'][0]['fecha'])
    assert FECHA_HORA.match(respuesta.get_json()['dispositivos'][0]['ultima_conexion'])


def test_availability_contract(client):
    login_as(client, 'user', 10)

    check_contract(client.get(f'/api/disponibilidad/1/{date.today().isoformat()}'), '/api/disponibilidad/{inst_id}/{fecha}', 'get')
    check_contract(client.get('/api/disponibilidad/1/mañana'), '/api/disponibilidad/{inst_id}/{fecha}', 'get')


def test_reservation_error_contract(client):
    login_as(client, 'user', 10)

    respuesta = client.post('/reservar', data={'instalacion_id': 1, 'fecha': 'x'})

    assert respuesta.status_code == 400
    check_contract(respuesta, '/reservar')


def test_denied_dates_are_local_text(client, monkeypatch):
    filas = [{'id': 1, 'rfid_uid': 'aabbccdd', 'fecha': datetime(2030, 1, 7, 15, 30, 5), 'usuario': 'Ana'}]

    class Cursor:
        execute = close = lambda self, *args: None
        fetchall = lambda self: filas

    class Conexion:
        cursor = lambda self, dictionary=False: Cursor()
        close = lambda self: None

    monkeypatch.setattr(database, 'get_db', Conexion)
    login_as(client, 'admin', 1)

    respuesta = client.get('/api/denegados')

    check_contract(respuesta, '/api/denegados', 'get')
    assert respuesta.get_json()['denegados'][0]['fecha'] == '07/01/2030 15:30:05'


def test_local_formats():
    assert fecha_local(date(2030, 1, 7)) == '07/01/2030'
    assert fecha_hora_local(datetime(2030, 1, 7, 15, 5, 9)) == '07/01/2030 15:05:09'
    assert fecha_hora_local(datetime(2030, 1, 7, 15, 5, 9), segundos=False) == '07/01/2030 15:05'


def test_reports_use_local_dates(client):
    log(datetime(2030, 1, 7, 15, 5, 9))
    with app.app_context():
        contenido = to_csv(reporte_bitacora(date(2030, 1, 1), date(2030, 1, 31)))

    assert '07/01/2030 15:05:09' in contenido and '2030-01-07' not in contenido


def test_my_reservations_use_local_dates(client):
    login_as(client, 'user', 10)
    with app.app_context():
        db.session.add(Reserva(user_id=10, instalacion_id=1, fecha_reserva=date(2030, 1, 7), hora_inicio=time(8, 0), hora_fin=time(9, 0)))
        db.session.commit()

    assert '07/01/2030' in client.get('/mis_reservas').get_data(as_text=True)
    assert '07/01/2030' in client.get('/instalaciones').get_data(as_text=True)


def test_screens_show_local_date_and_time(client):
    client.post('/historial', json={'uid': 'aabbccdd', 'instalacion_id': 1}, headers=DEVICE_HEADERS)
    with app.app_context():
        db.session.add(Notificacion(user_id=10, mensaje='Aviso', creado_en=datetime(2030, 1, 7, 15, 5)))
        db.session.commit()

    login_as(client, 'admin', 1)
    assert re.search(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}', client.get('/dispositivos').get_data(as_text=True))
    login_as(client, 'user', 10)
    assert '07/01/2030 15:05' in client.get('/notificaciones').get_data(as_text=True)


def test_notifications_use_local_dates(client):
    with app.app_context():
        reserva = Reserva(user_id=10, instalacion_id=1, fecha_reserva=date(2030, 1, 7), hora_inicio=time(8, 0), hora_fin=time(9, 0))
        reserva.instalacion = db.session.get(Instalacion, 1)
        assert '07/01/2030' in describir_reserva(reserva)
        db.session.rollback()


def test_retention_limit_is_24_months():
    assert fecha_limite(datetime(2030, 6, 15, 10, 0)) == datetime(2028, 6, 15, 10, 0)


def test_retention_limit_on_leap_day():
    assert fecha_limite(datetime(2028, 2, 29, 10, 0)) == datetime(2026, 2, 28, 10, 0)


def test_purge_removes_only_expired_records(client):
    ahora = datetime(2030, 6, 15, 10, 0)
    log(datetime(2028, 6, 15, 9, 59))
    log(datetime(2028, 6, 15, 10, 0))
    log(datetime(2030, 1, 1, 8, 0))

    with app.app_context():
        assert depurar_bitacora(ahora) == 1
        assert sorted(a.timestamp for a in AccessLog.query.all()) == [datetime(2028, 6, 15, 10, 0), datetime(2030, 1, 1, 8, 0)]


def test_purge_script_only_reports_by_default(client, capsys):
    log(datetime(2001, 1, 1, 8, 0))

    script_depuracion.main([])

    assert ': 1' in capsys.readouterr().out
    with app.app_context():
        assert AccessLog.query.count() == 1


def test_purge_script_deletes_when_applied(client):
    log(datetime(2001, 1, 1, 8, 0))

    script_depuracion.main(['--aplicar'])

    with app.app_context():
        assert AccessLog.query.count() == 0


def test_purge_is_recorded_in_security_log(client, monkeypatch):
    eventos = []
    monkeypatch.setattr('control_acceso.retencion.log_security_event', lambda tipo, **datos: eventos.append((tipo, datos)))

    with app.app_context():
        depurar_bitacora(datetime(2030, 6, 15, 10, 0))

    assert eventos == [('BITACORA_DEPURADA', {'details': 'Registros eliminados: 0'})]


@pytest.mark.parametrize('dia, esperado', [(date(2030, 1, 7), 'Lun'), (date(2030, 1, 13), 'Dom')])
def test_week_labels_are_spanish(dia, esperado):
    from control_acceso.formatos import DIAS_SEMANA

    assert DIAS_SEMANA[dia.weekday()] == esperado
