"""
Script de migración al modelo de datos de la especificación.
Agrega datos de usuarios y espacios, crea tarjetas y dispositivos, y registra el motivo de cada acceso.
Se puede ejecutar varias veces: cada paso comprueba si ya se aplicó.
"""
import hashlib
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Instalación configurada hoy en el firmware (INSTALACION_ID)
INSTALACION_LECTOR_ACTUAL = 2

COLUMNAS = {
    'users': [
        ('apellido', 'VARCHAR(45) NULL'),
        ('identificacion', 'VARCHAR(45) NULL UNIQUE'),
        ('email', 'VARCHAR(200) NULL UNIQUE'),
        ('rol', "VARCHAR(20) NOT NULL DEFAULT 'estudiante'"),
        ('estado', "VARCHAR(10) NOT NULL DEFAULT 'activo'"),
        ('autorizacion_datos', 'DATETIME NULL'),
        ('version_aviso', 'VARCHAR(10) NULL'),
        ('creado_en', 'DATETIME NULL DEFAULT CURRENT_TIMESTAMP'),
        ('actualizado_en', 'DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
    ],
    'instalaciones': [
        ('ubicacion', 'VARCHAR(45) NULL'),
        ('dotacion', 'VARCHAR(255) NULL'),
        ('estado', "VARCHAR(20) NOT NULL DEFAULT 'activo'"),
        ('roles_permitidos', 'VARCHAR(100) NULL'),
    ],
    'access_log': [
        ('motivo', 'VARCHAR(45) NULL'),
        ('dispositivo_id', 'INT NULL'),
    ],
}

def get_db():
    """Conexión a la base de datos"""
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.environ['DB_PASSWORD'],
        database=os.getenv('DB_NAME', 'control_acceso')
    )

def column_exists(cursor, table, column):
    cursor.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    return cursor.fetchone() is not None

def add_columns(cursor):
    for table, columns in COLUMNAS.items():
        for name, definition in columns:
            if not column_exists(cursor, table, name):
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                print(f"✓ Columna {table}.{name} agregada")

def create_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarjetas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            uid VARCHAR(20) NOT NULL UNIQUE,
            user_id INT NOT NULL,
            estado VARCHAR(10) NOT NULL DEFAULT 'activa',
            motivo_revocacion VARCHAR(20) NULL,
            fecha_asignacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_revocacion DATETIME NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dispositivos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            instalacion_id INT NOT NULL,
            descripcion VARCHAR(100) NULL,
            token_hash CHAR(64) NOT NULL UNIQUE,
            estado VARCHAR(10) NOT NULL DEFAULT 'activo',
            ultima_conexion DATETIME NULL,
            FOREIGN KEY (instalacion_id) REFERENCES instalaciones(id)
        )
    """)
    print("✓ Tablas tarjetas y dispositivos listas")

def link_access_log_to_devices(cursor):
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'fk_access_log_dispositivo'
    """)
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            ALTER TABLE access_log ADD CONSTRAINT fk_access_log_dispositivo
            FOREIGN KEY (dispositivo_id) REFERENCES dispositivos(id) ON DELETE SET NULL
        """)

def move_cards(cursor):
    """Pasa users.rfid a tarjetas y elimina la columna original"""
    if not column_exists(cursor, 'users', 'rfid'):
        return
    cursor.execute("""
        INSERT IGNORE INTO tarjetas (uid, user_id)
        SELECT LOWER(rfid), id FROM users
    """)
    print(f"✓ Tarjetas migradas: {cursor.rowcount}")
    cursor.execute("""
        SELECT COUNT(*) FROM users u
        LEFT JOIN tarjetas t ON t.user_id = u.id AND t.uid = LOWER(u.rfid)
        WHERE t.id IS NULL
    """)
    missing = cursor.fetchone()[0]
    if missing:
        raise RuntimeError(f"{missing} usuarios sin tarjeta migrada; no se elimina users.rfid")
    cursor.execute("ALTER TABLE users DROP COLUMN rfid")
    print("✓ Columna users.rfid eliminada")

def register_current_reader(cursor):
    """Conserva el token actual para no tener que reconfigurar el firmware"""
    token = os.getenv('DEVICE_TOKEN')
    cursor.execute("SELECT COUNT(*) FROM dispositivos")
    if not token or cursor.fetchone()[0] > 0:
        return
    cursor.execute(
        "INSERT INTO dispositivos (instalacion_id, descripcion, token_hash) VALUES (%s, %s, %s)",
        (INSTALACION_LECTOR_ACTUAL, 'Lector principal', hashlib.sha256(token.encode('utf-8')).hexdigest())
    )
    print(f"✓ Lector registrado para la instalación {INSTALACION_LECTOR_ACTUAL}")

def migrate_modelo():
    conn = get_db()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        add_columns(cursor)
        create_tables(cursor)
        link_access_log_to_devices(cursor)
        move_cards(cursor)
        register_current_reader(cursor)
        print("\nMigración completada")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("ADVERTENCIA: Asegúrese de tener un backup antes de continuar.")
    if input("¿Desea continuar? (s/n): ").lower() == 's':
        migrate_modelo()
    else:
        print("Migración cancelada.")
