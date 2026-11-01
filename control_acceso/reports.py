import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from .extensions import db
from .models import AccessLog, Instalacion, Reserva, User
from .reservations import HORA_APERTURA, HORA_CIERRE, DOMINGO

MAXIMO_DIAS_PERIODO = 366
DENEGACIONES_PARA_MARCAR = 3
VENTANA_DENEGACIONES = timedelta(minutes=10)
FILAS_EN_PANTALLA = 500
PREFIJOS_DE_FORMULA = ('=', '+', '-', '@')

HORAS_HABILES_POR_DIA = HORA_CIERRE.hour - HORA_APERTURA.hour


class PeriodoInvalido(Exception):
    pass


def validate_period(desde, hasta):
    if desde > hasta:
        raise PeriodoInvalido('La fecha inicial es posterior a la final')
    if (hasta - desde).days + 1 > MAXIMO_DIAS_PERIODO:
        raise PeriodoInvalido('El periodo máximo es de 366 días')


def decimal_es(valor):
    return f'{valor:.1f}'.replace('.', ',')


def porcentaje_ocupacion(horas_reservadas, horas_habiles):
    return round(horas_reservadas / horas_habiles * 100, 1) if horas_habiles else 0.0


def horas_de(reserva):
    return (datetime.combine(date.min, reserva.hora_fin) - datetime.combine(date.min, reserva.hora_inicio)).total_seconds() / 3600


def accesos_del_periodo(desde, hasta, exitoso, instalacion_id=None):
    consulta = AccessLog.query.filter(
        AccessLog.timestamp >= datetime.combine(desde, time.min),
        AccessLog.timestamp < datetime.combine(hasta + timedelta(days=1), time.min),
    )
    if exitoso is not None:
        consulta = consulta.filter(AccessLog.success.is_(exitoso))
    if instalacion_id:
        consulta = consulta.filter(AccessLog.instalacion_id == instalacion_id)
    return consulta.order_by(AccessLog.timestamp).all()


def reporte_ocupacion(desde, hasta, instalacion_id):
    reservas = Reserva.query.filter(
        Reserva.instalacion_id == instalacion_id,
        Reserva.fecha_reserva >= desde,
        Reserva.fecha_reserva <= hasta,
        Reserva.estado != 'cancelada',
    ).all()
    horas_reservadas = defaultdict(float)
    for reserva in reservas:
        horas_reservadas[reserva.fecha_reserva] += horas_de(reserva)
    horas_con_acceso = defaultdict(set)
    for acceso in accesos_del_periodo(desde, hasta, True, instalacion_id):
        horas_con_acceso[acceso.timestamp.date()].add(acceso.timestamp.hour)

    filas, puntos = [], []
    total_reservadas = total_con_acceso = total_habiles = 0
    for indice in range((hasta - desde).days + 1):
        dia = desde + timedelta(days=indice)
        habiles = 0 if dia.weekday() == DOMINGO else HORAS_HABILES_POR_DIA
        reservadas, con_acceso = horas_reservadas[dia], len(horas_con_acceso[dia])
        ocupacion = porcentaje_ocupacion(reservadas, habiles)
        total_reservadas += reservadas
        total_con_acceso += con_acceso
        total_habiles += habiles
        filas.append([dia.isoformat(), decimal_es(reservadas), con_acceso, habiles, decimal_es(ocupacion)])
        puntos.append((dia.isoformat(), ocupacion, f'{dia.isoformat()}: {decimal_es(ocupacion)} %'))

    if not total_reservadas and not total_con_acceso:
        filas = []
    else:
        filas.append(['Total', decimal_es(total_reservadas), total_con_acceso, total_habiles,
                      decimal_es(porcentaje_ocupacion(total_reservadas, total_habiles))])
    columnas = ['Fecha', 'Horas reservadas', 'Horas con acceso', 'Horas hábiles', 'Ocupación (%)']
    return {
        'tablas': [{'titulo': 'Ocupación por día', 'columnas': columnas, 'filas': filas}],
        'grafico': {'titulo': 'Ocupación diaria (%)', 'puntos': puntos if filas else [], 'maximo': 100},
    }


def reporte_uso(desde, hasta, instalacion_id=None):
    accesos = accesos_del_periodo(desde, hasta, True, instalacion_id)
    por_usuario = Counter(acceso.user_id for acceso in accesos)
    nombres = {u.id: f"{u.name} {u.apellido or ''}".strip() for u in
               User.query.filter(User.id.in_([id_ for id_ in por_usuario if id_ is not None])).all()}
    por_hora = Counter(acceso.timestamp.hour for acceso in accesos)

    filas_usuario = [[nombres.get(user_id, 'Usuario no disponible'), total] for user_id, total in por_usuario.most_common()]
    franja = lambda hora: f'{hora:02d}:00 a {hora + 1:02d}:00'
    filas_hora = [[franja(hora), por_hora[hora]] for hora in sorted(por_hora)]
    puntos = [(f'{hora:02d}', por_hora[hora], f'{franja(hora)}: {por_hora[hora]} accesos') for hora in range(24)]
    return {
        'tablas': [
            {'titulo': 'Accesos autorizados por usuario', 'columnas': ['Usuario', 'Accesos'], 'filas': filas_usuario},
            {'titulo': 'Accesos autorizados por franja', 'columnas': ['Franja', 'Accesos'], 'filas': filas_hora},
        ],
        'grafico': {'titulo': 'Accesos autorizados por hora', 'puntos': puntos if accesos else [],
                    'maximo': max(por_hora.values(), default=0)},
    }


def uids_marcados(momentos_por_uid):
    """UID con 3 o más denegaciones dentro de una ventana de 10 minutos"""
    marcados = []
    for uid, momentos in momentos_por_uid.items():
        ordenados = sorted(momentos)
        separacion = DENEGACIONES_PARA_MARCAR - 1
        for inicio, fin in zip(ordenados, ordenados[separacion:]):
            if fin - inicio <= VENTANA_DENEGACIONES:
                marcados.append([uid, inicio.strftime('%Y-%m-%d %H:%M:%S')])
                break
    return marcados


def nombres_de_espacios():
    return dict(db.session.query(Instalacion.id, Instalacion.nombre).all())


def reporte_denegados(desde, hasta):
    accesos = accesos_del_periodo(desde, hasta, False)
    espacios = nombres_de_espacios()
    grupos = Counter()
    momentos = defaultdict(list)
    for acceso in accesos:
        espacio = espacios.get(acceso.instalacion_id, 'Sin espacio')
        grupos[(acceso.motivo or 'Sin motivo registrado', espacio, acceso.rfid_uid or 'Sin UID')] += 1
        if acceso.rfid_uid:
            momentos[acceso.rfid_uid].append(acceso.timestamp)
    filas = [[*grupo, total] for grupo, total in grupos.most_common()]
    return {
        'tablas': [
            {'titulo': 'Denegaciones agrupadas', 'columnas': ['Motivo', 'Espacio', 'UID', 'Intentos'], 'filas': filas},
            {'titulo': 'UID señalados (3 o más denegaciones en 10 minutos)', 'columnas': ['UID', 'Inicio de la ventana'],
             'filas': uids_marcados(momentos)},
        ],
    }


def reporte_bitacora(desde, hasta, instalacion_id=None):
    espacios = nombres_de_espacios()
    usuarios = dict(db.session.query(User.id, User.name).all())
    filas = [[
        acceso.id, acceso.timestamp.strftime('%Y-%m-%d %H:%M:%S'), usuarios.get(acceso.user_id, 'No registrado'),
        acceso.rfid_uid or '', espacios.get(acceso.instalacion_id, 'Sin espacio'),
        'Autorizado' if acceso.success else 'Denegado', acceso.motivo or '',
    ] for acceso in reversed(accesos_del_periodo(desde, hasta, None, instalacion_id))]
    columnas = ['ID', 'Fecha y hora', 'Usuario', 'UID', 'Espacio', 'Resultado', 'Motivo']
    return {'tablas': [{'titulo': 'Bitácora de accesos', 'columnas': columnas, 'filas': filas}]}


def celda_segura(valor):
    """Evita que una hoja de cálculo interprete texto de usuarios como fórmula"""
    texto = str(valor)
    return f"'{texto}" if texto.startswith(PREFIJOS_DE_FORMULA) else texto


def to_csv(reporte):
    salida = io.StringIO(newline='')
    salida.write('﻿')
    escritor = csv.writer(salida, delimiter=';')
    for indice, tabla in enumerate(reporte['tablas']):
        if indice:
            escritor.writerow([])
        escritor.writerow(tabla['columnas'])
        escritor.writerows([celda_segura(celda) for celda in fila] for fila in tabla['filas'])
    return salida.getvalue()
