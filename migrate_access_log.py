"""
Script de migración para agregar columnas de métricas a la tabla access_log
"""
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def get_db():
    """Conexión a la base de datos"""
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', 'Roldan.1982'),
        database=os.getenv('DB_NAME', 'control_acceso')
    )

def migrate_access_log():
    """Agrega nuevas columnas a la tabla access_log"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Verificar si las columnas ya existen
        cursor.execute("SHOW COLUMNS FROM access_log LIKE 'rfid_uid'")
        rfid_exists = cursor.fetchone()
        
        cursor.execute("SHOW COLUMNS FROM access_log LIKE 'tiempo_lectura_ms'")
        tiempo_lectura_exists = cursor.fetchone()
        
        cursor.execute("SHOW COLUMNS FROM access_log LIKE 'tiempo_reconexion_wifi'")
        tiempo_reconexion_exists = cursor.fetchone()
        
        # Agregar columnas si no existen
        if not rfid_exists:
            cursor.execute("ALTER TABLE access_log ADD COLUMN rfid_uid VARCHAR(50)")
            print("✓ Columna rfid_uid agregada")
        else:
            print("✓ Columna rfid_uid ya existe")
        
        if not tiempo_lectura_exists:
            cursor.execute("ALTER TABLE access_log ADD COLUMN tiempo_lectura_ms INT")
            print("✓ Columna tiempo_lectura_ms agregada")
        else:
            print("✓ Columna tiempo_lectura_ms ya existe")
        
        if not tiempo_reconexion_exists:
            cursor.execute("ALTER TABLE access_log ADD COLUMN tiempo_reconexion_wifi INT")
            print("✓ Columna tiempo_reconexion_wifi agregada")
        else:
            print("✓ Columna tiempo_reconexion_wifi ya existe")
        
        conn.commit()
        print("\nMigración completada exitosamente")
        
    except Exception as e:
        print(f"Error durante la migración: {str(e)}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Iniciando migración de la tabla access_log...")
    print()
    migrate_access_log()
