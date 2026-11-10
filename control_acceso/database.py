import os

import mysql.connector

from .config import require_env

# Conexión directa para consultas legacy (Dashboard e Historial)
def get_db():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'control_acceso_def')
    )
