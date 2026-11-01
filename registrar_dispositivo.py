"""
Registra un lector para una instalación y muestra su token una única vez.
Uso: python registrar_dispositivo.py <instalacion_id> "<descripcion>"
"""
import hashlib
import mysql.connector
import os
import secrets
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def registrar_dispositivo(instalacion_id, descripcion):
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    cursor = conn.cursor()
    try:
        token = secrets.token_hex(32)
        cursor.execute(
            "INSERT INTO dispositivos (instalacion_id, descripcion, token_hash) VALUES (%s, %s, %s)",
            (instalacion_id, descripcion, hashlib.sha256(token.encode('utf-8')).hexdigest())
        )
        conn.commit()
        print(f"Lector {cursor.lastrowid} registrado. Copie este token en secrets.h; no se volverá a mostrar:")
        print(token)
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    registrar_dispositivo(int(sys.argv[1]), sys.argv[2])
