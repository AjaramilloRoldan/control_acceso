"""
Crea un administrador; la contraseña se pide por consola para no dejarla en el historial.
Uso: python crear_admin.py <usuario>
"""
import getpass
import sys

from app import app
from control_acceso.extensions import db
from control_acceso.models import Admin
from control_acceso.security import hash_password, log_security_event
from control_acceso.validators import validate_password, validate_username

def crear_admin(username, password):
    """Devuelve el mensaje de error, o None si el administrador quedó creado"""
    if not validate_username(username):
        return 'Usuario inválido (solo alfanuméricos y guiones bajos, 3-50 caracteres)'
    if not validate_password(password):
        return 'Contraseña inválida (mínimo 12 caracteres, con mayúsculas, minúsculas, dígitos y símbolos)'

    db.create_all()
    if Admin.query.filter_by(username=username).first():
        return f'Ya existe un administrador con el usuario {username}'

    admin = Admin(username=username, password=hash_password(password))
    db.session.add(admin)
    db.session.commit()
    log_security_event('ADMIN_CREATED', user_id=admin.id, details=f'Username: {username}')
    return None

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    contrasena = getpass.getpass('Contraseña: ')
    if contrasena != getpass.getpass('Repite la contraseña: '):
        sys.exit('Las contraseñas no coinciden')
    with app.app_context():
        error = crear_admin(sys.argv[1], contrasena)
    if error:
        sys.exit(error)
    print(f'Administrador {sys.argv[1]} creado')
