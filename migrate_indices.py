"""
Script de migración de índices.
Agrega los índices por fecha de la bitácora y de las reservas.
Se puede ejecutar varias veces; omite los índices que ya existen.
"""
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

INDICES = (
    ('access_log', 'idx_access_log_instalacion_fecha', '(instalacion_id, timestamp)'),
    ('access_log', 'idx_access_log_fecha', '(timestamp)'),
    ('reservas', 'idx_reservas_instalacion_fecha', '(instalacion_id, fecha_reserva)'),
)

def migrate_indices():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    cursor = conn.cursor()
    try:
        for tabla, indice, columnas in INDICES:
            cursor.execute(f"SHOW INDEX FROM {tabla} WHERE Key_name = %s", (indice,))
            if cursor.fetchall():
                print(f"El índice {indice} ya existe")
                continue
            cursor.execute(f"ALTER TABLE {tabla} ADD INDEX {indice} {columnas}")
            print(f"Índice {indice} creado")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate_indices()
