"""
Script de migración de notificaciones.
Crea la tabla de la bandeja de notificaciones de la plataforma.
Se puede ejecutar varias veces.
"""
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def migrate_notificaciones():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notificaciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                mensaje VARCHAR(255) NOT NULL,
                leida BOOLEAN NOT NULL DEFAULT FALSE,
                creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_notificaciones_usuario (user_id, leida),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        print("✓ Tabla notificaciones lista")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("ADVERTENCIA: Asegúrese de tener un backup antes de continuar.")
    if input("¿Desea continuar? (s/n): ").lower() == 's':
        migrate_notificaciones()
    else:
        print("Migración cancelada.")
