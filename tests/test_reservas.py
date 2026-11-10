import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from test_security import DEVICE_HEADERS, client, login_as  # noqa: F401
from app import app
from control_acceso.access import evaluate_access
from control_acceso.extensions import db
from control_acceso.models import Instalacion, Reserva, Tarjeta, User
from control_acceso.reservations import (HORA_CIERRE, ReservaError, cancelar_reserva, crear_reserva,
                                         modificar_reserva, parse_serie, programar_series, read_series_csv)
from control_acceso.security import hash_password

LUNES = date(2030, 1, 7)
AHORA = datetime(2030, 1, 1, 8, 0)
CARGA = {'id_usuario': '20', 'id_espacios': '1', 'dia_semana': '2', 'hora_inicio': '08:00', 'hora_fin': '10:00',
         'fecha_inicial': '2030-02-05', 'fecha_final': '2030-05-30'}


@pytest.fixture
def people(client):
    with app.app_context():
        db.session.add(User(id=20, name='Dora', username='dora', rol='docente', password=hash_password('clave123'), autorizacion_datos=datetime(2026, 1, 1), version_aviso='1.0'))
        db.session.add(User(id=21, name='Aseo', username='aseo', rol='administrativo', password=hash_password('clave123'), autorizacion_datos=datetime(2026, 1, 1), version_aviso='1.0'))
        db.session.add(Tarjeta(uid='20202020', user_id=20))
        db.session.add(Tarjeta(uid='21212121', user_id=21))
        db.session.commit()
    return client


def book(user_id=11, fecha=LUNES, inicio=time(14, 0), fin=time(16, 0), instalacion_id=1, ahora=AHORA):
    return crear_reserva(db.session.get(User, user_id), instalacion_id, fecha, inicio, fin, None, ahora)


def status_of(callable_):
    with pytest.raises(ReservaError) as error:
        callable_()
    db.session.rollback()
    return error.value.status


def tomorrow_form(**overrides):
    manana = datetime.now(ZoneInfo('America/Bogota')).date() + timedelta(days=1)
    while manana.weekday() == 6:
        manana += timedelta(days=1)
    return {'instalacion_id': 1, 'fecha': manana.isoformat(), 'hora_inicio': '10:00', 'hora_fin': '11:00', **overrides}


def test_free_slot_is_confirmed(client):
    with app.app_context():
        assert book().estado == 'activa'


def test_student_view_renders_uploaded_installation_image(client):
    with app.app_context():
        db.session.get(Instalacion, 1).imagen = 'sala.jpg'
        db.session.commit()

    login_as(client, 'user', 11)
    html = client.get('/instalaciones').get_data(as_text=True)

    assert 'src="/static/uploads/instalaciones/sala.jpg"' in html


@pytest.mark.parametrize('inicio, fin, status', [
    (time(15, 0), time(17, 0), 409),
    (time(13, 0), time(14, 30), 409),
    (time(14, 30), time(15, 0), 409),
    (time(16, 0), time(17, 0), None),
    (time(12, 0), time(14, 0), None),
])
def test_overlap_uses_half_open_intervals(client, inicio, fin, status):
    with app.app_context():
        book()
        if status:
            assert status_of(lambda: book(10, inicio=inicio, fin=fin)) == status
        else:
            assert book(10, inicio=inicio, fin=fin).id


@pytest.mark.parametrize('fecha, inicio, fin', [
    (date(2029, 12, 31), time(10, 0), time(11, 0)),
    (date(2030, 1, 6), time(10, 0), time(11, 0)),
    (LUNES, time(5, 0), time(7, 0)),
    (LUNES, time(21, 0), time(1, 0)),
    (LUNES, time(10, 0), time(10, 15)),
    (LUNES, time(10, 0), time(14, 30)),
    (LUNES, time(11, 0), time(10, 0)),
])
def test_invalid_slot_is_rejected(client, fecha, inicio, fin):
    with app.app_context():
        assert status_of(lambda: book(fecha=fecha, inicio=inicio, fin=fin)) == 400


def test_duration_limits_are_inclusive(client):
    with app.app_context():
        assert book(inicio=time(6, 0), fin=time(6, 30)).id
        assert book(inicio=time(18, 0), fin=time(22, 0)).id
        assert book(inicio=time(22, 0), fin=HORA_CIERRE).id


def test_space_policy_applies_to_requests(client):
    with app.app_context():
        db.session.get(Instalacion, 1).roles_permitidos = 'docente'
        db.session.commit()
        assert status_of(book) == 403
        db.session.get(Instalacion, 1).roles_permitidos = None
        db.session.get(Instalacion, 1).estado = 'fuera_servicio'
        db.session.commit()
        assert status_of(book) == 409


def test_administrative_staff_cannot_request_reservations(people):
    with app.app_context():
        assert status_of(lambda: book(21)) == 403


def test_request_returns_error_message_as_json(client):
    login_as(client, 'user', 11)
    assert client.post('/reservar', data=tomorrow_form()).status_code == 201
    response = client.post('/reservar', data=tomorrow_form())
    assert response.status_code == 409 and 'no disponible' in response.get_json()['error']
    assert client.post('/reservar', data=tomorrow_form(fecha='no-es-fecha')).status_code == 400


def test_midnight_is_accepted_as_reservation_end(client):
    login_as(client, 'user', 11)
    formulario = tomorrow_form(hora_inicio='20:00', hora_fin='00:00')
    response = client.post('/reservar', data=formulario)
    assert response.status_code == 201
    with app.app_context():
        reserva = db.session.get(Reserva, response.get_json()['id'])
        assert reserva.hora_fin == HORA_CIERRE
    ocupados = client.get(f"/api/disponibilidad/1/{formulario['fecha']}").get_json()
    assert ocupados[0]['to'] == '00:00'


def test_modification_deadline_is_sixty_minutes(client):
    with app.app_context():
        reserva = book()
        limite = datetime.combine(LUNES, time(13, 0))
        modificar_reserva(reserva, LUNES, time(15, 0), time(16, 0), limite - timedelta(minutes=1))
        assert reserva.hora_inicio == time(15, 0)
        tarde = datetime.combine(LUNES, time(14, 30))
        assert status_of(lambda: modificar_reserva(reserva, LUNES, time(17, 0), time(18, 0), tarde)) == 409


def test_modification_rechecks_overlap_but_ignores_itself(client):
    with app.app_context():
        reserva = book()
        book(10, inicio=time(17, 0), fin=time(18, 0))
        modificar_reserva(reserva, LUNES, time(15, 0), time(16, 0), AHORA)
        assert status_of(lambda: modificar_reserva(reserva, LUNES, time(16, 0), time(17, 30), AHORA)) == 409


def test_only_owner_or_admin_modifies(client):
    login_as(client, 'user', 11)
    reserva_id = client.post('/reservar', data=tomorrow_form()).get_json()['id']
    nuevo = tomorrow_form(hora_inicio='12:00', hora_fin='13:00')
    login_as(client, 'user', 10)
    assert client.post(f'/reservas/{reserva_id}', data=nuevo).status_code == 403
    login_as(client, 'admin', 1)
    assert client.post(f'/reservas/{reserva_id}', data=nuevo).status_code == 200


def test_cancelled_reservation_frees_slot_and_denies_access(client):
    with app.app_context():
        reserva = book()
        cancelar_reserva(reserva, AHORA)
        assert book(10).id
        momento = datetime.combine(LUNES, time(14, 5))
        instalacion = db.session.get(Instalacion, 1)
        assert evaluate_access('ddeeff00', instalacion, momento)[1] == 'SIN_RESERVA_VIGENTE'


def test_started_reservation_cannot_be_cancelled(client):
    with app.app_context():
        reserva = book()
        assert status_of(lambda: cancelar_reserva(reserva, datetime.combine(LUNES, time(14, 0)))) == 409


def test_academic_load_creates_weekly_series(people):
    with app.app_context():
        serie = parse_serie({**CARGA, 'fecha_inicial': '2030-02-05', 'fecha_final': '2030-05-28'}, 'carga_academica')
        assert programar_series([serie], AHORA) == 17
        reservas = Reserva.query.filter_by(user_id=20).all()
        assert {r.tipo for r in reservas} == {'carga_academica'}
        assert len({r.id_recurrencia for r in reservas}) == 1
        assert all(r.fecha_reserva.weekday() == 1 for r in reservas)
        momento = datetime(2030, 2, 12, 8, 5)
        assert evaluate_access('20202020', db.session.get(Instalacion, 1), momento)[1] is None


def test_series_with_conflict_creates_nothing(people):
    with app.app_context():
        book(inicio=time(8, 0), fin=time(10, 0), fecha=date(2030, 3, 5))
        serie = parse_serie(CARGA, 'carga_academica')
        with pytest.raises(ReservaError) as error:
            programar_series([serie], AHORA)
        db.session.rollback()
        assert error.value.status == 409 and '05/03/2030' in error.value.message
        assert Reserva.query.filter_by(user_id=20).count() == 0


@pytest.mark.parametrize('tipo, usuario', [('carga_academica', '11'), ('franja_operativa', '20')])
def test_series_requires_matching_role(people, tipo, usuario):
    with app.app_context():
        serie = parse_serie({**CARGA, 'id_usuario': usuario}, tipo)
        assert status_of(lambda: programar_series([serie], AHORA)) == 400


def test_operational_slot_grants_access_only_in_its_window(people):
    with app.app_context():
        campos = {**CARGA, 'id_usuario': '21', 'dia_semana': '3', 'hora_inicio': '06:00', 'hora_fin': '07:00',
                  'fecha_inicial': '2030-02-06', 'fecha_final': '2030-02-06'}
        programar_series([parse_serie(campos, 'franja_operativa')], AHORA)
        db.session.get(Instalacion, 1).estado = 'mantenimiento'
        db.session.commit()
        instalacion = db.session.get(Instalacion, 1)
        assert evaluate_access('21212121', instalacion, datetime(2030, 2, 6, 6, 10))[1] is None
        assert evaluate_access('21212121', instalacion, datetime(2030, 2, 6, 7, 10))[1] is not None


def test_maintenance_denies_regular_reservations(client):
    with app.app_context():
        book()
        db.session.get(Instalacion, 1).estado = 'mantenimiento'
        db.session.commit()
        momento = datetime.combine(LUNES, time(14, 5))
        assert evaluate_access('ddeeff00', db.session.get(Instalacion, 1), momento)[1] == 'ESPACIO_NO_OPERATIVO'


def test_csv_reports_invalid_row():
    contenido = ('id_usuario,id_espacios,dia_semana,hora_inicio,hora_fin,fecha_inicial,fecha_final\n'
                 '20,1,2,08:00,10:00,2030-02-05,2030-05-30\n'
                 '20,1,9,08:00,10:00,2030-02-05,2030-05-30\n').encode('utf-8')
    with pytest.raises(ReservaError) as error:
        read_series_csv(contenido, 'carga_academica')
    assert error.value.status == 400 and error.value.message.startswith('Fila 3:')


def test_admin_uploads_csv_program(people):
    login_as(client=people, role='admin', user_id=1)
    hoy = datetime.now(ZoneInfo('America/Bogota')).date()
    inicio, fin = hoy + timedelta(days=1), hoy + timedelta(days=30)
    contenido = ('﻿id_usuario,id_espacios,dia_semana,hora_inicio,hora_fin,fecha_inicial,fecha_final\n'
                 f'20,1,2,08:00,10:00,{inicio},{fin}\n').encode('utf-8')
    data = {'tipo': 'carga_academica', 'archivo': (io.BytesIO(contenido), 'carga.csv')}
    response = people.post('/reservas/recurrentes', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200 and 'Programación registrada'.encode() in response.data
    assert 'Dora'.encode() in people.get('/reservas/recurrentes').data


def test_program_page_requires_admin(people):
    login_as(people, 'user', 11)
    assert people.post('/reservas/recurrentes', data={}).status_code == 403
    login_as(people, 'admin', 1)
    assert people.post('/reservas/recurrentes', data={'tipo': 'x'}).status_code == 400


def test_my_reservations_shows_only_own_and_filters(client):
    with app.app_context():
        book(11)
        reserva = book(11, inicio=time(16, 0), fin=time(17, 0))
        book(10, inicio=time(18, 0), fin=time(19, 0))
        cancelar_reserva(reserva, AHORA)
    login_as(client, 'user', 11)
    pagina = client.get('/mis_reservas').data.decode()
    assert '14:00' in pagina and '16:00' in pagina and '18:00' not in pagina
    canceladas = client.get('/mis_reservas?estado=cancelada').data.decode()
    assert '16:00 — 17:00' in canceladas and '14:00 — 16:00' not in canceladas


def test_my_reservations_rejects_inverted_range(client):
    login_as(client, 'user', 11)
    assert client.get('/mis_reservas?fecha_desde=2030-02-01&fecha_hasta=2030-01-01').status_code == 400


def test_past_active_reservation_is_shown_as_completed(client):
    with app.app_context():
        assert db.session.get(Reserva, 1).estado_actual(datetime(2099, 1, 1)) == 'completada'


def test_availability_can_exclude_own_reservation(client):
    login_as(client, 'user', 11)
    formulario = tomorrow_form()
    reserva_id = client.post('/reservar', data=formulario).get_json()['id']
    url = f"/api/disponibilidad/1/{formulario['fecha']}"
    assert len(client.get(url).get_json()) == 1
    assert client.get(f'{url}?excluir={reserva_id}').get_json() == []


def test_user_pages_render(people):
    login_as(people, 'user', 21)
    assert 'Tu rol no reserva'.encode() in people.get('/instalaciones').data
    login_as(people, 'user', 20)
    assert 'Reservar Espacio'.encode() in people.get('/instalaciones').data
