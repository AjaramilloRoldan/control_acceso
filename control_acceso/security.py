import hashlib
import logging
import os
from logging.handlers import RotatingFileHandler

import bcrypt

security_logger = logging.getLogger('security')

def configure_security_log():
    if security_logger.handlers:
        return

    if not os.path.exists('logs'):
        os.makedirs('logs')

    security_logger.setLevel(logging.INFO)

    # Handler para archivo de seguridad con rotación
    security_handler = RotatingFileHandler(
        'logs/security.log',
        maxBytes=1024*1024,  # 1MB
        backupCount=5
    )
    security_handler.setLevel(logging.INFO)

    # Formato del log
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    security_handler.setFormatter(formatter)
    security_logger.addHandler(security_handler)

def log_security_event(event_type, user_id=None, details=None, ip=None):
    """Registra eventos de seguridad"""
    message = f"{event_type}"
    if user_id:
        message += f" | User ID: {user_id}"
    if details:
        message += f" | Details: {details}"
    if ip:
        message += f" | IP: {ip}"
    security_logger.info(message)

# --- UTILIDADES DE PASSWORD CON BCRYPT ---

def hash_password(password):
    """Hashea una contraseña usando bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password, hashed_password):
    """Verifica una contraseña contra su hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError:
        log_security_event('INVALID_PASSWORD_HASH', details='Ejecutar migrate_passwords.py')
        return False

def hash_device_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
