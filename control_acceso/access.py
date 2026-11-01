from datetime import timedelta

from .models import Reserva, Tarjeta

MARGEN_ACCESO_MINUTOS = 10

def evaluate_access(uid, instalacion, ahora):
    """Aplica las condiciones de autorización en orden; devuelve (usuario, motivo de denegación)"""
    tarjeta = Tarjeta.query.filter_by(uid=uid).first()
    if tarjeta is None:
        return None, 'TARJETA_NO_REGISTRADA'

    user = tarjeta.usuario
    if tarjeta.estado != 'activa':
        return user, 'TARJETA_REVOCADA'
    if user.estado != 'activo':
        return user, 'USUARIO_INACTIVO'
    if user.autorizacion_datos is None:
        return user, 'SIN_AUTORIZACION_DATOS'
    if instalacion.estado not in ('activo', 'mantenimiento'):
        return user, 'ESPACIO_NO_OPERATIVO'
    if user.rol not in instalacion.roles_autorizados:
        return user, 'ROL_NO_AUTORIZADO'

    fin_del_dia = ahora.replace(hour=23, minute=59, second=59)
    apertura = min(ahora + timedelta(minutes=MARGEN_ACCESO_MINUTOS), fin_del_dia).time()
    reservas = Reserva.query.filter(
        Reserva.user_id == user.id,
        Reserva.instalacion_id == instalacion.id,
        Reserva.fecha_reserva == ahora.date(),
        Reserva.hora_inicio <= apertura,
        Reserva.hora_fin > ahora.time(),
        Reserva.estado == 'activa'
    )
    if instalacion.estado == 'mantenimiento':
        franja = reservas.filter(Reserva.tipo == 'franja_operativa').first()
        return user, None if franja else 'ESPACIO_NO_OPERATIVO'
    return user, None if reservas.first() else 'SIN_RESERVA_VIGENTE'
