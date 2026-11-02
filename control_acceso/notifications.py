import logging
import os
import smtplib
import threading
import time
from email.message import EmailMessage

from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .formatos import fecha_local
from .models import Notificacion

logger = logging.getLogger(__name__)

MAX_INTENTOS_CORREO = 3
ESPERA_REINTENTO_SEGUNDOS = 5
TIEMPO_ESPERA_SMTP_SEGUNDOS = 10
ASUNTO = 'Control de Acceso UCP: notificación de reserva'


def send_email(destino, asunto, cuerpo):
    mensaje = EmailMessage()
    mensaje['Subject'] = asunto
    mensaje['From'] = os.getenv('SMTP_FROM') or os.getenv('SMTP_USER')
    mensaje['To'] = destino
    mensaje.set_content(cuerpo)
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')),
                      timeout=TIEMPO_ESPERA_SMTP_SEGUNDOS) as servidor:
        servidor.starttls()
        if os.getenv('SMTP_USER'):
            servidor.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        servidor.send_message(mensaje)


def deliver_email(user_id, destino, cuerpo):
    for intento in range(1, MAX_INTENTOS_CORREO + 1):
        try:
            send_email(destino, ASUNTO, cuerpo)
            return True
        except (smtplib.SMTPException, OSError):
            logger.warning('Intento %s de correo fallido para el usuario %s', intento, user_id)
            if intento < MAX_INTENTOS_CORREO:
                time.sleep(ESPERA_REINTENTO_SEGUNDOS)
    logger.error('No se pudo enviar el correo al usuario %s tras %s intentos', user_id, MAX_INTENTOS_CORREO)
    return False


def notificar(usuario, mensaje):
    """Registra la notificación y envía el correo; un fallo aquí no revierte la operación de origen"""
    user_id, destino = usuario.id, usuario.email
    try:
        db.session.add(Notificacion(user_id=user_id, mensaje=mensaje))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception('No se pudo registrar la notificación del usuario %s', user_id)
    if destino and os.getenv('SMTP_HOST'):
        threading.Thread(target=deliver_email, args=(user_id, destino, mensaje), daemon=True).start()


def describir_reserva(reserva):
    franja = f"{reserva.hora_inicio.strftime('%H:%M')} a {reserva.hora_fin.strftime('%H:%M')}"
    return f'{reserva.instalacion.nombre}, {fecha_local(reserva.fecha_reserva)}, de {franja}'


def notificar_reserva(reserva, evento):
    notificar(reserva.usuario, f'Tu reserva fue {evento}: {describir_reserva(reserva)}.')
