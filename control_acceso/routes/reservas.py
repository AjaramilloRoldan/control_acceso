from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, session, url_for)

from ..extensions import db
from ..models import Instalacion, Reserva, User
from ..reservations import (ROL_POR_TIPO, ROLES_CON_RESERVA, ReservaError, cancelar_reserva, check_manager,
                            crear_reserva, hora_actual, modificar_reserva, parse_date, parse_serie, parse_time,
                            programar_series, read_series_csv)

bp = Blueprint('reservas', __name__)

TIPOS_RESERVA = {'individual': 'Individual', 'carga_academica': 'Carga académica', 'franja_operativa': 'Franja operativa'}
ESTADOS_RESERVA = {'activa': 'Confirmada', 'completada': 'Completada', 'cancelada': 'Cancelada'}

def session_user():
    if session.get('role') != 'user':
        return None
    return db.session.get(User, session.get('user_id'))

@bp.errorhandler(ReservaError)
def handle_reserva_error(error):
    db.session.rollback()
    return jsonify({"error": error.message}), error.status

@bp.route('/instalaciones')
def instalaciones():
    if 'user_id' not in session: return redirect(url_for('auth.login'))

    usuario = session_user()
    lista_inst = Instalacion.query.filter_by(estado='activo').all()
    mis_reservas = []
    reservables = set()
    if usuario:
        mis_reservas = Reserva.query.filter(
            Reserva.user_id == usuario.id,
            Reserva.estado == 'activa',
            Reserva.fecha_reserva >= hora_actual().date()
        ).order_by(Reserva.fecha_reserva, Reserva.hora_inicio).all()
        if usuario.rol in ROLES_CON_RESERVA:
            reservables = {inst.id for inst in lista_inst if usuario.rol in inst.roles_autorizados}

    return render_template('instalaciones.html',
                           instalaciones=lista_inst,
                           mis_reservas=mis_reservas,
                           reservables=reservables,
                           gestiona_reservas=bool(usuario and usuario.rol in ROLES_CON_RESERVA),
                           nombre_usuario=session.get('name'))

@bp.route('/reservar', methods=['POST'])
def reservar():
    if session.get('role') != 'user': return redirect(url_for('auth.login'))

    reserva = crear_reserva(
        session_user(),
        request.form.get('instalacion_id', type=int),
        parse_date(request.form.get('fecha')),
        parse_time(request.form.get('hora_inicio')),
        parse_time(request.form.get('hora_fin')),
        request.form.get('motivo'),
        hora_actual()
    )
    return jsonify({"id": reserva.id}), 201

@bp.route('/reservas/<int:reserva_id>', methods=['POST'])
def modificar(reserva_id):
    reserva = Reserva.query.get_or_404(reserva_id)
    check_manager(reserva, session_user(), session.get('role') == 'admin')
    modificar_reserva(
        reserva,
        parse_date(request.form.get('fecha')),
        parse_time(request.form.get('hora_inicio')),
        parse_time(request.form.get('hora_fin')),
        hora_actual()
    )
    return jsonify({"id": reserva.id})

@bp.route('/cancelar_reserva/<int:reserva_id>', methods=['POST'])
def cancelar(reserva_id):
    reserva = Reserva.query.get_or_404(reserva_id)
    check_manager(reserva, session_user(), session.get('role') == 'admin')
    cancelar_reserva(reserva, hora_actual())
    return jsonify({"id": reserva.id})

@bp.route('/mis_reservas')
def mis_reservas():
    if session.get('role') != 'user': return redirect(url_for('auth.login'))

    filtros = {clave: request.args.get(clave, '') for clave in ('estado', 'fecha_desde', 'fecha_hasta')}
    ahora = hora_actual()
    consulta = Reserva.query.filter_by(user_id=session['user_id'])
    try:
        desde = parse_date(filtros['fecha_desde']) if filtros['fecha_desde'] else None
        hasta = parse_date(filtros['fecha_hasta']) if filtros['fecha_hasta'] else None
    except ReservaError as error:
        return render_mis_reservas(filtros, [], error.message), 400
    if desde and hasta and desde > hasta:
        return render_mis_reservas(filtros, [], 'La fecha inicial es posterior a la final'), 400
    if desde:
        consulta = consulta.filter(Reserva.fecha_reserva >= desde)
    if hasta:
        consulta = consulta.filter(Reserva.fecha_reserva <= hasta)

    reservas = [(r, r.estado_actual(ahora)) for r in
                consulta.order_by(Reserva.fecha_reserva.desc(), Reserva.hora_inicio.desc()).all()]
    if filtros['estado']:
        reservas = [fila for fila in reservas if fila[1] == filtros['estado']]
    return render_mis_reservas(filtros, reservas)

def render_mis_reservas(filtros, reservas, error=None):
    return render_template('mis_reservas.html', filtros=filtros, reservas=reservas, error=error,
                           estados=ESTADOS_RESERVA, tipos=TIPOS_RESERVA)

def scheduled_series():
    series = {}
    reservas = Reserva.query.filter(Reserva.id_recurrencia.isnot(None), Reserva.estado == 'activa') \
        .order_by(Reserva.fecha_reserva).all()
    for reserva in reservas:
        serie = series.setdefault(reserva.id_recurrencia, {
            'tipo': reserva.tipo, 'usuario': reserva.usuario.name, 'espacio': reserva.instalacion.nombre,
            'hora_inicio': reserva.hora_inicio, 'hora_fin': reserva.hora_fin,
            'desde': reserva.fecha_reserva, 'ocurrencias': 0,
        })
        serie['hasta'] = reserva.fecha_reserva
        serie['ocurrencias'] += 1
    return list(series.values())

def render_recurrentes(error=None):
    usuarios = User.query.filter(User.estado == 'activo', User.rol.in_(ROL_POR_TIPO.values())).order_by(User.name).all()
    espacios = Instalacion.query.filter(Instalacion.estado.in_(('activo', 'mantenimiento'))).all()
    tipos = {tipo: TIPOS_RESERVA[tipo] for tipo in ROL_POR_TIPO}
    return render_template('reservas_recurrentes.html', error=error, usuarios=usuarios, instalaciones=espacios,
                           tipos=tipos, series=scheduled_series())

def series_from_request(tipo):
    if tipo not in ROL_POR_TIPO:
        raise ReservaError('Tipo de programación inválido', 400)
    archivo = request.files.get('archivo')
    if archivo and archivo.filename:
        return read_series_csv(archivo.read(), tipo)
    espacios = request.form.getlist('id_espacios')
    if not espacios or (tipo == 'carga_academica' and len(espacios) > 1):
        raise ReservaError('Selecciona un espacio para la carga académica o al menos uno para la franja', 400)
    return [parse_serie({**request.form.to_dict(), 'id_espacios': espacio}, tipo) for espacio in espacios]

@bp.route('/reservas/recurrentes', methods=['GET', 'POST'])
def recurrentes():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    if request.method == 'GET':
        return render_recurrentes()

    try:
        creadas = programar_series(series_from_request(request.form.get('tipo')), hora_actual())
    except ReservaError as error:
        db.session.rollback()
        return render_recurrentes(error.message), error.status
    flash(f'Programación registrada: {creadas} ocurrencia(s)', 'success')
    return redirect(url_for('reservas.recurrentes'))

@bp.route('/api/disponibilidad/<int:inst_id>/<fecha>')
def consultar_disponibilidad(inst_id, fecha):
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    try:
        fecha_consulta = datetime.strptime(fecha, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
    excluir = request.args.get('excluir', type=int)
    reservas = Reserva.query.filter_by(instalacion_id=inst_id, fecha_reserva=fecha_consulta, estado='activa').all()
    ocupados = [{"from": r.hora_inicio.strftime('%H:%M'), "to": r.hora_fin.strftime('%H:%M')}
                for r in reservas if r.id != excluir]
    return jsonify(ocupados)
