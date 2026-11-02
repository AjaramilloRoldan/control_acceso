import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from test_reservas import AHORA, LUNES, book, people  # noqa: F401
from test_security import client, login_as  # noqa: F401
from app import app
from control_acceso import notifications
from control_acceso.extensions import db
from control_acceso.models import AccessLog, Instalacion, Notificacion, Reserva, User
from control_acceso.reports import (celda_segura, porcentaje_ocupacion, reporte_denegados, reporte_ocupacion, reporte_uso,
                                    to_csv, uids_marcados)
from control_acceso.reservations import cancelar_reserva, modificar_reserva, parse_serie, programar_series
from test_reservas import CARGA


def log(momento, success=True, uid='aabbccdd', user_id=10, instalacion_id=1, motivo=None):
    db.session.add(AccessLog(user_id=user_id, rfid_uid=uid, instalacion_id=instalacion_id, success=success,
                             motivo=motivo, timestamp=momento))


def messages(user_id):
    return [n.mensaje for n in Notificacion.query.filter_by(user_id=user_id).order_by(Notificacion.id).all()]


def edit_form(**overrides):
    return {'nombre': 'Squash', 'descripcion': '', 'capacidad': '4', 'estado': 'activo',
            'roles_permitidos': ['estudiante', 'docente', 'administrativo'], **overrides}


def test_default_timestamps_use_colombian_time(client):
    with app.app_context():
        db.session.add(Notificacion(user_id=10, mensaje='hora'))
        db.session.commit()
        creada = Notificacion.query.filter_by(mensaje='hora').one().creado_en
        assert abs(creada - datetime.now(ZoneInfo('America/Bogota')).replace(tzinfo=None)) < timedelta(minutes=1)


def test_reservation_lifecycle_notifies_owner(client):
    with app.app_context():
        reserva = book()
        modificar_reserva(reserva, LUNES, time(15, 0), time(16, 0), AHORA)
        cancelar_reserva(reserva, AHORA)
        eventos = messages(11)
        assert [m.split(':')[0] for m in eventos] == ['Tu reserva fue confirmada', 'Tu reserva fue modificada', 'Tu reserva fue cancelada']
        assert 'Squash' in eventos[0] and '07/01/2030' in eventos[0] and '14:00 a 16:00' in eventos[0]


def test_series_sends_one_summary(people):
    with app.app_context():
        programar_series([parse_serie(CARGA, 'carga_academica')], AHORA)
        assert len(messages(20)) == 1


def test_mail_failure_keeps_reservation_and_is_logged(client, monkeypatch, caplog):
    def failing_send(*_):
        raise OSError('servidor caído')
    monkeypatch.setattr(notifications, 'send_email', failing_send)
    monkeypatch.setattr(notifications.time, 'sleep', lambda _: None)
    with caplog.at_level(logging.ERROR):
        assert notifications.deliver_email(11, 'a@ucp.edu.co', 'mensaje') is False
    assert 'tras 3 intentos' in caplog.text


def test_mail_is_retried_until_delivered(client, monkeypatch):
    intentos = []

    def flaky_send(*_):
        intentos.append(1)
        if len(intentos) < 3:
            raise OSError('intermitente')
    monkeypatch.setattr(notifications, 'send_email', flaky_send)
    monkeypatch.setattr(notifications.time, 'sleep', lambda _: None)
    assert notifications.deliver_email(11, 'a@ucp.edu.co', 'mensaje') is True
    assert len(intentos) == 3


def test_mail_is_sent_only_when_configured(client, monkeypatch):
    enviados = []
    monkeypatch.setattr(notifications, 'deliver_email', lambda *args: enviados.append(args))
    monkeypatch.setattr(notifications.threading, 'Thread',
                        lambda target, args, daemon: type('T', (), {'start': lambda self: target(*args)})())
    with app.app_context():
        usuario = db.session.get(User, 10)
        monkeypatch.delenv('SMTP_HOST', raising=False)
        notifications.notificar(usuario, 'sin smtp')
        assert enviados == []
        monkeypatch.setenv('SMTP_HOST', 'smtp.test')
        notifications.notificar(usuario, 'con smtp')
        assert enviados == [(10, 'ana@ucp.edu.co', 'con smtp')]


def test_inbox_shows_only_own_and_marks_read(client):
    with app.app_context():
        db.session.add(Notificacion(user_id=10, mensaje='propia'))
        db.session.add(Notificacion(user_id=11, mensaje='ajena'))
        db.session.commit()
    login_as(client, 'user', 10)
    pagina = client.get('/notificaciones').data.decode()
    assert 'propia' in pagina and 'ajena' not in pagina
    assert 'Notificaciones (1)' in client.get('/instalaciones').data.decode()
    client.post('/notificaciones/leidas')
    with app.app_context():
        assert Notificacion.query.filter_by(user_id=10, leida=False).count() == 0
        assert Notificacion.query.filter_by(user_id=11, leida=False).count() == 1


def test_maintenance_notifies_holders_of_future_reservations(client):
    with app.app_context():
        fecha = date.today() + timedelta(days=30)
        fecha += timedelta(days=fecha.weekday() == 6)
        book(10, fecha=fecha, inicio=time(9, 0), fin=time(10, 0), ahora=datetime(2020, 1, 1))
        Notificacion.query.delete()
        db.session.commit()
    login_as(client, 'admin', 1)
    client.post('/editar_instalacion/1', data=edit_form(estado='mantenimiento'))
    with app.app_context():
        assert db.session.get(Instalacion, 1).estado == 'mantenimiento'
        assert any('mantenimiento' in m for m in messages(10))


def test_admin_sets_space_role_policy(client):
    login_as(client, 'admin', 1)
    client.post('/editar_instalacion/1', data=edit_form(roles_permitidos=['docente']))
    with app.app_context():
        assert db.session.get(Instalacion, 1).roles_permitidos == 'docente'
    client.post('/editar_instalacion/1', data=edit_form())
    with app.app_context():
        assert db.session.get(Instalacion, 1).roles_permitidos is None


@pytest.mark.parametrize('overrides', [{'roles_permitidos': []}, {'roles_permitidos': ['admin']}, {'estado': 'baja'}])
def test_invalid_space_changes_are_rejected(client, overrides):
    login_as(client, 'admin', 1)
    client.post('/editar_instalacion/1', data=edit_form(nombre='Cambiada', **overrides))
    with app.app_context():
        assert db.session.get(Instalacion, 1).nombre == 'Squash'


def test_occupancy_percentage():
    assert porcentaje_ocupacion(32, 80) == 40.0
    assert porcentaje_ocupacion(0, 0) == 0.0


def test_occupancy_report_by_day(client):
    with app.app_context():
        book(inicio=time(8, 0), fin=time(12, 0))
        cancelada = book(inicio=time(14, 0), fin=time(16, 0))
        cancelar_reserva(cancelada, AHORA)
        log(datetime(2030, 1, 7, 8, 5))
        log(datetime(2030, 1, 7, 8, 50))
        log(datetime(2030, 1, 7, 9, 1))
        log(datetime(2030, 1, 7, 10, 0), success=False)
        db.session.commit()
        filas = reporte_ocupacion(date(2030, 1, 6), date(2030, 1, 7), 1)['tablas'][0]['filas']
        assert filas[0] == ['06/01/2030', '0,0', 0, 0, '0,0']
        assert filas[1] == ['07/01/2030', '4,0', 2, 16, '25,0']
        assert filas[2] == ['Total', '4,0', 2, 16, '25,0']


def test_occupancy_without_data_is_empty(client):
    with app.app_context():
        reporte = reporte_ocupacion(date(2030, 1, 6), date(2030, 1, 7), 1)
        assert reporte['tablas'][0]['filas'] == [] and reporte['grafico']['puntos'] == []


def test_usage_report_counts_hourly_slots(client):
    with app.app_context():
        for minuto in range(12):
            log(datetime(2030, 1, 7, 8, minuto * 4))
        log(datetime(2030, 1, 7, 9, 0), user_id=11)
        log(datetime(2030, 1, 7, 8, 1), success=False)
        db.session.commit()
        usuarios, franjas = reporte_uso(date(2030, 1, 7), date(2030, 1, 7))['tablas']
        assert usuarios['filas'] == [['Ana', 12], ['Luis', 1]]
        assert ['08:00 a 09:00', 12] in franjas['filas']


def test_three_denials_in_ten_minutes_are_flagged():
    base = datetime(2030, 1, 7, 10, 0)
    assert uids_marcados({'a': [base, base + timedelta(minutes=4), base + timedelta(minutes=9)]})[0][0] == 'a'
    assert uids_marcados({'a': [base, base + timedelta(minutes=4), base + timedelta(minutes=11)]}) == []
    assert uids_marcados({'a': [base, base + timedelta(minutes=1)]}) == []


def test_denied_report_groups_by_reason_space_and_uid(client):
    with app.app_context():
        log(datetime(2030, 1, 7, 10, 0), False, motivo='TARJETA_REVOCADA')
        log(datetime(2030, 1, 7, 10, 4), False, motivo='TARJETA_REVOCADA')
        log(datetime(2030, 1, 7, 10, 9), False)
        log(datetime(2030, 1, 7, 10, 9), True)
        db.session.commit()
        grupos, marcados = reporte_denegados(date(2030, 1, 7), date(2030, 1, 7))['tablas']
        assert ['TARJETA_REVOCADA', 'Squash', 'aabbccdd', 2] in grupos['filas']
        assert ['Sin motivo registrado', 'Squash', 'aabbccdd', 1] in grupos['filas']
        assert marcados['filas'][0][0] == 'aabbccdd'


def test_csv_uses_bom_semicolon_and_header():
    contenido = to_csv({'tablas': [{'columnas': ['Ocupación', 'Valor'], 'filas': [['Ñandú', 1], ['=2+2', 2]]}]})
    lineas = contenido.splitlines()
    assert contenido.startswith('﻿') and lineas[0] == '﻿Ocupación;Valor'
    assert lineas[1] == 'Ñandú;1' and lineas[2] == "'=2+2;2"
    assert celda_segura(5) == '5'


def test_export_has_one_line_per_record_plus_header(client):
    with app.app_context():
        for segundo in range(25):
            log(datetime(2030, 1, 7, 8, 0, segundo))
        db.session.commit()
    login_as(client, 'admin', 1)
    response = client.get('/reportes?tipo=bitacora&fecha_desde=2030-01-07&fecha_hasta=2030-01-07&formato=csv')
    assert response.mimetype == 'text/csv' and 'attachment' in response.headers['Content-Disposition']
    assert len(response.data.decode('utf-8').splitlines()) == 26


@pytest.mark.parametrize('query, status', [
    ('tipo=ocupacion', 200), ('tipo=uso', 200), ('tipo=denegados', 200), ('tipo=bitacora', 200),
    ('fecha_desde=2030-02-01&fecha_hasta=2030-01-01', 400),
    ('fecha_desde=2028-01-01&fecha_hasta=2030-01-01', 400),
    ('fecha_desde=no-es-fecha', 400),
])
def test_report_page_validates_period(client, query, status):
    login_as(client, 'admin', 1)
    assert client.get(f'/reportes?{query}').status_code == status


def test_reports_require_admin(client):
    login_as(client, 'user', 10)
    assert client.get('/reportes').status_code == 302
    with app.app_context():
        assert Reserva.query.count() == 1
