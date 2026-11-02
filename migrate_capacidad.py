"""
Script de migración de espacios.
Agrega la capacidad y exige que el nombre del espacio sea único.
Se puede ejecutar varias veces; si hay nombres repetidos se detiene sin crear el índice.
"""
import mysql.connector
import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

NOMBRE_INDICE = 'uq_instalaciones_nombre'

def migrate_capacidad():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM instalaciones LIKE 'capacidad'")
        if not cursor.fetchall():
            cursor.execute("ALTER TABLE instalaciones ADD COLUMN capacidad INT NULL")
            print("Columna capacidad agregada")

        cursor.execute("SHOW INDEX FROM instalaciones WHERE Key_name = %s", (NOMBRE_INDICE,))
        if cursor.fetchall():
            print("El índice de nombre ya existe")
            return

        cursor.execute("SELECT nombre FROM instalaciones GROUP BY nombre HAVING COUNT(*) > 1")
        repetidos = [fila[0] for fila in cursor.fetchall()]
        if repetidos:
            sys.exit(f"Corrige estos nombres repetidos y vuelve a ejecutar: {repetidos}")

        cursor.execute(f"ALTER TABLE instalaciones ADD UNIQUE INDEX {NOMBRE_INDICE} (nombre)")
        print("Índice de nombre creado")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate_capacidad()
