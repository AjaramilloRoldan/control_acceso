"""
Script de migración para identificar la instalación de cada acceso
"""
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def migrate_metricas():
    """Agrega access_log.instalacion_id; los registros anteriores quedan en NULL"""
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    cursor = conn.cursor()

    try:
        cursor.execute("SHOW COLUMNS FROM access_log LIKE 'instalacion_id'")
        if cursor.fetchone():
            print("✓ Columna instalacion_id ya existe")
            return

        cursor.execute("""
            ALTER TABLE access_log
            ADD COLUMN instalacion_id INT NULL,
            ADD CONSTRAINT fk_access_log_instalacion
                FOREIGN KEY (instalacion_id) REFERENCES instalaciones(id) ON DELETE SET NULL
        """)
        print("✓ Columna instalacion_id agregada")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate_metricas()
