import re
import time as reloj
from datetime import datetime, timedelta

import pytest

from test_lectores import log
from test_modelo import change, new_user_form
from test_security import ADMIN_PASSWORD, client, login_as  # noqa: F401
from app import app
from control_acceso import config
from control_acceso.extensions import db
from control_acceso.models import Instalacion, User
from control_acceso.reports import FILAS_POR_PAGINA
from control_acceso.security import hash_password


def add_users(cantidad):
    with app.app_context():
        for indice in range(cantidad):
            db.session.add(User(name=f'Persona {indice:02}', username=f'persona{indice}', password='x', rol='docente'))
        db.session.commit()


def space_form(**overrides):
    return {'nombre': 'Aula 301', 'ubicacion': 'Bloque A', 'capacidad': '30', 'dotacion': 'Proyector', **overrides}


def edit_form(**overrides):
    return {**space_form(), 'estado': 'activo', 'roles_permitidos': ['estudiante'], **overrides}


def names_in(response):
    return re.findall(r'<h3 class="text-white font-bold leading-tight">(.*?)</h3>', response.get_data(as_text=True))


def spaces_in(response):
    return re.findall(r'<h3 class="text-2xl font-bold text-white mb-3">(.*?)</h3>', response.get_data(as_text=True))


def seed_spaces():
    with app.app_context():
        db.session.add(Instalacion(nombre='Aula Grande', ubicacion='Bloque A', capacidad=100, dotacion='Proyector y sonido'))
        db.session.add(Instalacion(nombre='Aula Chica', ubicacion='Bloque B', capacidad=10, dotacion='Tablero'))
        db.session.commit()


def test_login_starts_session_of_eight_hours(client):
    client.post('/login', data={'username': 'admin', 'password': ADMIN_PASSWORD})

    with client.session_transaction() as sesion:
        assert sesion.permanent
        restante = sesion['expira_en'] - reloj.time()
    assert config.DURACION_SESION.total_seconds() - 60 < restante <= timedelta(hours=8).total_seconds()
    assert app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(hours=8)


def test_expired_session_is_closed(client):
    login_as(client, 'admin', 1)
    with client.session_transaction() as sesion:
        sesion['expira_en'] = reloj.time() - 1

    assert client.get('/usuarios').headers['Location'].endswith('/login')
    with client.session_transaction() as sesion:
        assert 'role' not in sesion


def test_activity_does_not_extend_session(client):
    client.post('/login', data={'username': 'admin', 'password': ADMIN_PASSWORD})
    with client.session_transaction() as sesion:
        expira_en = sesion['expira_en']

    client.get('/usuarios')

    with client.session_transaction() as sesion:
        assert sesion['expira_en'] == expira_en


def test_users_are_paginated(client):
    add_users(FILAS_POR_PAGINA + 3)
    login_as(client, 'admin', 1)

    assert len(names_in(client.get('/usuarios'))) == FILAS_POR_PAGINA
    assert len(names_in(client.get('/usuarios?pagina=2'))) == 5


@pytest.mark.parametrize('campo, valor', [('name', 'Valen'), ('apellido', 'Valen'), ('identificacion', '10881'), ('email', 'valen@')])
def test_search_matches_partial_fields(client, campo, valor):
    change(User, 11, **{campo: {'identificacion': '1088123456', 'email': 'valen@ucp.edu.co'}.get(campo, 'Valentina')})
    login_as(client, 'admin', 1)

    nombres = names_in(client.get(f'/usuarios?q={valor}'))

    assert len(nombres) == 1


def test_search_treats_wildcards_as_text(client):
    login_as(client, 'admin', 1)

    assert names_in(client.get('/usuarios?q=%25')) == []


def test_users_filter_by_role_and_state(client):
    change(User, 11, rol='docente', estado='inactivo')
    login_as(client, 'admin', 1)

    assert names_in(client.get('/usuarios')) == ['Ana']
    assert names_in(client.get('/usuarios?estado=inactivo')) == ['Luis']
    assert names_in(client.get('/usuarios?estado=todos&rol=docente')) == ['Luis']


def test_inactive_user_has_no_delete_action(client):
    change(User, 11, estado='inactivo')
    login_as(client, 'admin', 1)

    html = client.get('/usuarios?estado=inactivo').get_data(as_text=True)

    assert '/eliminar_usuario/11' not in html and 'Usuario inactivo' in html


def test_user_pagination_keeps_filters(client):
    add_users(FILAS_POR_PAGINA + 1)
    login_as(client, 'admin', 1)

    assert 'rol=docente' in client.get('/usuarios?rol=docente').get_data(as_text=True).split('Siguiente')[0][-300:]


def test_space_stores_capacity_and_details(client):
    login_as(client, 'admin', 1)

    client.post('/crear_instalacion', data=space_form())

    with app.app_context():
        espacio = Instalacion.query.filter_by(nombre='Aula 301').one()
        assert (espacio.capacidad, espacio.ubicacion, espacio.dotacion) == (30, 'Bloque A', 'Proyector')


@pytest.mark.parametrize('form', [{'capacidad': '0'}, {'capacidad': '501'}, {'capacidad': ''}, {'capacidad': 'x'},
                                  {'nombre': '   '}, {'ubicacion': 'x' * 46}, {'dotacion': 'x' * 256}])
def test_invalid_space_is_rejected(client, form):
    login_as(client, 'admin', 1)

    client.post('/crear_instalacion', data=space_form(**form))

    with app.app_context():
        assert Instalacion.query.count() == 1


def test_space_name_must_be_unique(client):
    login_as(client, 'admin', 1)

    client.post('/crear_instalacion', data=space_form(nombre='Squash'))

    with app.app_context():
        assert Instalacion.query.filter_by(nombre='Squash').count() == 1


def test_editing_to_repeated_name_keeps_original(client):
    login_as(client, 'admin', 1)
    client.post('/crear_instalacion', data=space_form())

    client.post('/editar_instalacion/1', data=edit_form())

    with app.app_context():
        assert db.session.get(Instalacion, 1).nombre == 'Squash'


def test_editing_updates_details(client):
    login_as(client, 'admin', 1)

    client.post('/editar_instalacion/1', data=edit_form(nombre='Squash', capacidad='12'))

    with app.app_context():
        assert db.session.get(Instalacion, 1).capacidad == 12


@pytest.mark.parametrize('consulta, esperados', [
    ('capacidad_min=50', ['Aula Grande']),
    ('dotacion=sonido', ['Aula Grande']),
    ('ubicacion=Bloque%20B', ['Aula Chica']),
    ('capacidad_min=5&ubicacion=Bloque', ['Aula Grande', 'Aula Chica']),
])
def test_spaces_filter_by_attributes(client, consulta, esperados):
    seed_spaces()
    login_as(client, 'user', 10)

    assert sorted(spaces_in(client.get(f'/instalaciones?{consulta}'))) == sorted(esperados)


def test_filtered_csv_contains_only_matching_rows(client):
    log(datetime(2030, 1, 7, 10, 0), False, motivo='ROL_NO_AUTORIZADO')
    log(datetime(2030, 1, 7, 11, 0), True)
    login_as(client, 'admin', 1)

    respuesta = client.get('/historial?formato=csv&resultado=denegado')

    filas = respuesta.get_data(as_text=True).strip().splitlines()
    assert respuesta.headers['Content-Type'] == 'text/csv; charset=utf-8'
    assert len(filas) == 2 and 'ROL_NO_AUTORIZADO' in filas[1]


def test_user_csv_contains_only_own_records(client):
    log(datetime(2030, 1, 7, 10, 0), user_id=10)
    log(datetime(2030, 1, 7, 11, 0), user_id=11)
    login_as(client, 'user', 10)

    assert len(client.get('/historial?formato=csv').get_data(as_text=True).strip().splitlines()) == 2


def test_csv_link_keeps_filters(client):
    login_as(client, 'admin', 1)

    html = client.get('/historial?resultado=denegado&pagina=1').get_data(as_text=True)

    assert re.search(r'href="/historial\?[^"]*formato=csv[^"]*resultado=denegado|href="/historial\?[^"]*resultado=denegado[^"]*formato=csv', html)


def test_user_with_authorization_can_withdraw_it(client):
    login_as(client, 'user', 10)

    assert b'No autorizo' in client.get('/autorizacion').data
    client.post('/autorizacion', data={'decision': 'rechazar'})

    with app.app_context():
        assert db.session.get(User, 10).autorizacion_datos is None


def test_new_user_form_still_works(client):
    login_as(client, 'admin', 1)

    client.post('/agregar_usuario', data=new_user_form(password='Clave-Segura-123'))

    with app.app_context():
        usuario = User.query.filter_by(username='eva').one()
        assert usuario.password != hash_password('Clave-Segura-123')
