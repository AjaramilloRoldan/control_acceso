import re

from .models import ROLES_USUARIO

LONGITUD_MINIMA_CONTRASENA = 12

def validate_username(username):
    """Valida que el username cumpla con los requisitos"""
    if not username or len(username) < 3 or len(username) > 50:
        return False
    # Solo permitir caracteres alfanuméricos y guiones bajos
    return all(c.isalnum() or c == '_' for c in username)

def validate_password(password):
    """Valida la longitud y las clases de caracteres exigidas para la contraseña"""
    if not password or len(password) < LONGITUD_MINIMA_CONTRASENA:
        return False
    return all(re.search(clase, password) for clase in (r'[a-z]', r'[A-Z]', r'\d', r'[^a-zA-Z0-9]'))

def normalize_uid(uid):
    """Representa el UID en hexadecimal, en minúsculas y sin separadores"""
    return re.sub(r'[\s:-]', '', uid).lower()

def validate_rfid(rfid):
    """Valida el formato del UID ya normalizado"""
    return bool(re.fullmatch(r'[0-9a-f]{8,20}', rfid or ''))

def validate_email(email):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email or '')) and len(email) <= 200

def read_personal_data(form, required):
    """Lee los datos personales del formulario; devuelve (datos, error)"""
    datos = {
        'apellido': form.get('apellido', '').strip(),
        'identificacion': form.get('identificacion', '').strip(),
        'email': form.get('email', '').strip().lower(),
    }
    rol = form.get('rol', 'estudiante')
    if required and not all(datos.values()):
        return None, 'Error: Apellido, identificación y correo son obligatorios'
    if len(datos['apellido']) > 45:
        return None, 'Error: Apellido inválido (máximo 45 caracteres)'
    if datos['identificacion'] and not re.fullmatch(r'\d{6,10}', datos['identificacion']):
        return None, 'Error: Identificación inválida (solo dígitos, entre 6 y 10)'
    if datos['email'] and not validate_email(datos['email']):
        return None, 'Error: Correo electrónico inválido'
    if rol not in ROLES_USUARIO:
        return None, 'Error: Rol inválido'
    return {**{clave: valor or None for clave, valor in datos.items()}, 'rol': rol}, None

def validate_name(name):
    """Valida el nombre del usuario"""
    if not name or len(name) < 2 or len(name) > 100:
        return False
    return True
