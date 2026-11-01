import os
import time
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'Falta la variable de entorno obligatoria {name}. Revisa .env.example')
    return value

# Configuración de Zona Horaria para Colombia
if hasattr(time, 'tzset'):
    os.environ['TZ'] = 'America/Bogota'
    time.tzset()

UPLOAD_FOLDER = 'static/uploads/instalaciones'

def database_uri():
    db_host = os.getenv('DB_HOST', 'localhost')
    db_user = os.getenv('DB_USER', 'root')
    db_name = os.getenv('DB_NAME', 'control_acceso')
    return os.getenv('DATABASE_URL') or (
        f"mysql+mysqlconnector://{db_user}:{quote_plus(require_env('DB_PASSWORD'))}@{db_host}:3306/{db_name}"
    )
