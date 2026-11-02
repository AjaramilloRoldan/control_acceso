import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import config
from .extensions import db
from .formatos import fecha_local
from .models import Instalacion, Reserva, User
from .notifications import notificar, notificar_reserva

HORA_APERTURA = time(6, 0)
HORA_CIERRE = time(22, 0)
DURACION_MINIMA_MINUTOS = 30
DURACION_MAXIMA_MINUTOS = 240
MOTIVO_MAXIMO = 200
DOMINGO = 6
ROLES_CON_RESERVA = ('estudiante', 'docente')
ROL_POR_TIPO = {'carga_academica': 'docente', 'franja_operativa': 'administrativo'}
ESTADOS_ESPACIO_POR_TIPO = {'carga_academica': ('activo',), 'franja_operativa': ('activo', 'mantenimiento')}


class ReservaError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Serie:
    tipo: str
    usuario_id: int
    instalacion_id: int
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    fecha_inicial: date
    fecha_final: date


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ReservaError('Fecha inválida', 400)


def parse_time(value):
    try:
        return datetime.strptime(value, '%H:%M').time()
    except (TypeError, ValueError):
        raise ReservaError('Hora inválida', 400)


def validate_schedule(inicio, fin):
    """Horario institucional y duración permitida (supuesto S-03)"""
    if inicio < HORA_APERTURA or fin > HORA_CIERRE:
        raise ReservaError('El horario permitido es de 06:00 a 22:00', 400)
    minutos = (datetime.combine(date.min, fin) - datetime.combine(date.min, inicio)).total_seconds() / 60
    if not DURACION_MINIMA_MINUTOS <= minutos <= DURACION_MAXIMA_MINUTOS:
        raise ReservaError('La duración debe estar entre 30 minutos y 4 horas', 400)


def validate_slot(fecha, inicio, fin, ahora):
    validate_schedule(inicio, fin)
    if fecha.weekday() == DOMINGO:
        raise ReservaError('No se admiten reservas los domingos', 400)
    if datetime.combine(fecha, inicio) < ahora:
        raise ReservaError('La fecha de la reserva ya pasó', 400)


def lock_instalacion(instalacion_id):
    """Serializa las reservas de un espacio para que la verificación y el registro sean atómicos"""
    return Instalacion.query.filter_by(id=instalacion_id).with_for_update().populate_existing().first()


def find_conflict(instalacion_id, fecha, inicio, fin, excluir_id=None):
    """Intersección de intervalos [inicio, fin). La lectura con bloqueo ve lo último confirmado"""
    consulta = Reserva.query.filter(
        Reserva.instalacion_id == instalacion_id,
        Reserva.fecha_reserva == fecha,
        Reserva.estado == 'activa',
        Reserva.hora_inicio < fin,
        Reserva.hora_fin > inicio,
    )
    if excluir_id is not None:
        consulta = consulta.filter(Reserva.id != excluir_id)
    return consulta.with_for_update().first()


def check_available(instalacion_id, fecha, inicio, fin, excluir_id=None):
    conflicto = find_conflict(instalacion_id, fecha, inicio, fin, excluir_id)
    if conflicto:
        franja = f"{conflicto.hora_inicio.strftime('%H:%M')} a {conflicto.hora_fin.strftime('%H:%M')}"
        raise ReservaError(f'Horario no disponible: ya está reservado de {franja}', 409)


def check_policy(usuario, instalacion):
    if instalacion is None or instalacion.estado == 'baja':
        raise ReservaError('Instalación no encontrada', 404)
    if instalacion.estado != 'activo':
        raise ReservaError('La instalación no está disponible', 409)
    if usuario.rol not in instalacion.roles_autorizados:
        raise ReservaError('Tu rol no está autorizado para esta instalación', 403)


def check_requester(usuario):
    if usuario is None or usuario.estado != 'activo' or usuario.rol not in ROLES_CON_RESERVA:
        raise ReservaError('No autorizado para gestionar reservas', 403)


def check_manager(reserva, usuario, es_admin):
    """Autoriza al administrador o al titular cuyo rol gestiona reservas"""
    if es_admin:
        return
    check_requester(usuario)
    if reserva.user_id != usuario.id:
        raise ReservaError('No autorizado', 403)


def clean_motivo(motivo):
    motivo = (motivo or '').strip()
    if len(motivo) > MOTIVO_MAXIMO:
        raise ReservaError('El motivo admite máximo 200 caracteres', 400)
    return motivo or None


def crear_reserva(usuario, instalacion_id, fecha, inicio, fin, motivo, ahora):
    check_requester(usuario)
    motivo = clean_motivo(motivo)
    instalacion = lock_instalacion(instalacion_id)
    check_policy(usuario, instalacion)
    validate_slot(fecha, inicio, fin, ahora)
    check_available(instalacion.id, fecha, inicio, fin)
    reserva = Reserva(user_id=usuario.id, instalacion_id=instalacion.id, fecha_reserva=fecha,
                      hora_inicio=inicio, hora_fin=fin, motivo=motivo)
    db.session.add(reserva)
    db.session.commit()
    notificar_reserva(reserva, 'confirmada')
    return reserva


def modificar_reserva(reserva, fecha, inicio, fin, ahora):
    if reserva.estado != 'activa':
        raise ReservaError('La reserva no está vigente', 409)
    if ahora > reserva.inicio - timedelta(minutes=config.PLAZO_MODIFICACION_MINUTOS):
        raise ReservaError('Plazo de modificación vencido', 409)
    instalacion = lock_instalacion(reserva.instalacion_id)
    check_policy(reserva.usuario, instalacion)
    validate_slot(fecha, inicio, fin, ahora)
    check_available(instalacion.id, fecha, inicio, fin, excluir_id=reserva.id)
    reserva.fecha_reserva = fecha
    reserva.hora_inicio = inicio
    reserva.hora_fin = fin
    db.session.commit()
    notificar_reserva(reserva, 'modificada')


def cancelar_reserva(reserva, ahora):
    if reserva.estado != 'activa' or ahora >= reserva.inicio:
        raise ReservaError('La reserva ya inició o no está vigente', 409)
    reserva.estado = 'cancelada'
    db.session.commit()
    notificar_reserva(reserva, 'cancelada')


def parse_serie(campos, tipo):
    try:
        serie = Serie(
            tipo=tipo,
            usuario_id=int(campos['id_usuario']),
            instalacion_id=int(campos['id_espacios']),
            dia_semana=int(campos['dia_semana']),
            hora_inicio=parse_time(campos['hora_inicio']),
            hora_fin=parse_time(campos['hora_fin']),
            fecha_inicial=parse_date(campos['fecha_inicial']),
            fecha_final=parse_date(campos['fecha_final']),
        )
    except (KeyError, TypeError, ValueError):
        raise ReservaError('Datos de la programación incompletos o inválidos', 400)
    if not 1 <= serie.dia_semana <= 6:
        raise ReservaError('El día de la semana debe estar entre 1 (lunes) y 6 (sábado)', 400)
    if serie.fecha_final < serie.fecha_inicial:
        raise ReservaError('La fecha final es anterior a la inicial', 400)
    validate_schedule(serie.hora_inicio, serie.hora_fin)
    return serie


def read_series_csv(contenido, tipo):
    """Lee un CSV con las columnas de la programación; los errores indican la fila"""
    try:
        texto = contenido.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ReservaError('El archivo debe estar en UTF-8', 400)
    series = []
    for fila, campos in enumerate(csv.DictReader(io.StringIO(texto)), start=2):
        try:
            series.append(parse_serie(campos, tipo))
        except ReservaError as error:
            raise ReservaError(f'Fila {fila}: {error.message}', 400)
    if not series:
        raise ReservaError('El archivo no tiene filas', 400)
    return series


def occurrences(serie):
    fecha = serie.fecha_inicial + timedelta(days=(serie.dia_semana - 1 - serie.fecha_inicial.weekday()) % 7)
    while fecha <= serie.fecha_final:
        yield fecha
        fecha += timedelta(days=7)


def check_serie(serie, instalaciones, ahora):
    usuario = db.session.get(User, serie.usuario_id)
    rol = ROL_POR_TIPO[serie.tipo]
    if usuario is None or usuario.estado != 'activo' or usuario.rol != rol:
        raise ReservaError(f'El usuario {serie.usuario_id} no está activo con rol {rol}', 400)
    instalacion = instalaciones.get(serie.instalacion_id)
    if instalacion is None or instalacion.estado not in ESTADOS_ESPACIO_POR_TIPO[serie.tipo]:
        raise ReservaError(f'La instalación {serie.instalacion_id} no está disponible', 409)
    if serie.fecha_inicial < ahora.date():
        raise ReservaError('La fecha inicial ya pasó', 400)


def programar_series(series, ahora):
    """Crea todas las ocurrencias o ninguna; devuelve cuántas se crearon"""
    instalaciones = {id_: lock_instalacion(id_) for id_ in sorted({s.instalacion_id for s in series})}
    conflictos = []
    creadas = 0
    for serie in series:
        check_serie(serie, instalaciones, ahora)
        primera = None
        for fecha in occurrences(serie):
            if find_conflict(serie.instalacion_id, fecha, serie.hora_inicio, serie.hora_fin):
                conflictos.append(fecha)
                continue
            reserva = Reserva(user_id=serie.usuario_id, instalacion_id=serie.instalacion_id, fecha_reserva=fecha,
                              hora_inicio=serie.hora_inicio, hora_fin=serie.hora_fin, tipo=serie.tipo)
            db.session.add(reserva)
            db.session.flush()
            primera = primera or reserva
            reserva.id_recurrencia = primera.id
            creadas += 1
    if conflictos:
        raise ReservaError('Conflicto en las fechas: ' + ', '.join(fecha_local(fecha) for fecha in sorted(set(conflictos))), 409)
    if not creadas:
        raise ReservaError('El periodo no incluye ese día de la semana', 400)
    db.session.commit()
    for serie in series:
        notificar(db.session.get(User, serie.usuario_id),
                  f'Se programó tu horario en {instalaciones[serie.instalacion_id].nombre}: '
                  f"del {fecha_local(serie.fecha_inicial)} al {fecha_local(serie.fecha_final)}, "
                  f"de {serie.hora_inicio.strftime('%H:%M')} a {serie.hora_fin.strftime('%H:%M')}.")
    return creadas
