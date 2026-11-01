"""
Script de migración de reservas.
Agrega el tipo de reserva, el identificador de recurrencia y el motivo.
Se puede ejecutar varias veces: cada paso comprueba si ya se aplicó.
"""
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

COLUMNAS = [
    ('tipo', "VARCHAR(20) NOT NULL DEFAULT 'individual'"),
    ('id_recurrencia', 'INT NULL'),
    ('motivo', 'VARCHAR(200) NULL'),
]

def migrate_reservas():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        for name, definition in COLUMNAS:
            cursor.execute("SHOW COLUMNS FROM reservas LIKE %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(f"ALTER TABLE reservas ADD COLUMN {name} {definition}")
                print(f"✓ Columna reservas.{name} agregada")
        print("\nMigración completada")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("ADVERTENCIA: Asegúrese de tener un backup antes de continuar.")
    if input("¿Desea continuar? (s/n): ").lower() == 's':
        migrate_reservas()
    else:
        print("Migración cancelada.")
