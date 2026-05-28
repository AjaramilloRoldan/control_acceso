"""
Script para verificar configuración de zona horaria del sistema
"""
import mysql.connector
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import time

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

def check_timezone():
    """Verifica configuración de zona horaria"""
    print("=" * 60)
    print("VERIFICACIÓN DE ZONA HORARIA")
    print("=" * 60)
    
    # 1. Zona horaria del sistema Python
    print("\n1. ZONA HORARIA PYTHON:")
    print(f"   Hora local: {datetime.now()}")
    print(f"   Hora UTC: {datetime.now(timezone.utc)}")
    print(f"   Timezone: {time.tzname}")
    print(f"   Offset UTC: {time.timezone / 3600} horas")
    
    # 2. Zona horaria de MySQL
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    print("\n2. ZONA HORARIA MYSQL:")
    cursor.execute("SELECT @@global.time_zone as global_tz, @@session.time_zone as session_tz")
    tz_info = cursor.fetchone()
    print(f"   Global timezone: {tz_info['global_tz']}")
    print(f"   Session timezone: {tz_info['session_tz']}")
    
    cursor.execute("SELECT NOW() as mysql_now, UTC_TIMESTAMP() as mysql_utc")
    time_info = cursor.fetchone()
    print(f"   MySQL NOW(): {time_info['mysql_now']}")
    print(f"   MySQL UTC_TIMESTAMP(): {time_info['mysql_utc']}")
    
    # 3. Verificar reserva de Alejandro
    print("\n3. RESERVA DE ALEJANDRO:")
    cursor.execute("""
        SELECT r.id, r.fecha_reserva, r.hora_inicio, r.hora_fin, r.estado,
               i.nombre as instalacion
        FROM reservas r
        JOIN instalaciones i ON r.instalacion_id = i.id
        JOIN users u ON r.user_id = u.id
        WHERE u.name LIKE '%Alejandro%' AND r.fecha_reserva = CURDATE()
        ORDER BY r.id DESC
        LIMIT 1
    """)
    reserva = cursor.fetchone()
    
    if reserva:
        print(f"   ID Reserva: {reserva['id']}")
        print(f"   Instalación: {reserva['instalacion']}")
        print(f"   Fecha: {reserva['fecha_reserva']}")
        print(f"   Hora inicio: {reserva['hora_inicio']}")
        print(f"   Hora fin: {reserva['hora_fin']}")
        print(f"   Estado: {reserva['estado']}")
        print(f"   Hora actual Python: {datetime.now().time()}")
        print(f"   Hora actual MySQL: {time_info['mysql_now'].time()}")
        
        # Verificar si la hora actual está dentro del rango
        hora_actual = datetime.now().time()
        # Convertir timedelta a time si es necesario
        if isinstance(reserva['hora_inicio'], timedelta):
            hora_inicio = (datetime.min + reserva['hora_inicio']).time()
        else:
            hora_inicio = reserva['hora_inicio']
        
        if isinstance(reserva['hora_fin'], timedelta):
            hora_fin = (datetime.min + reserva['hora_fin']).time()
        else:
            hora_fin = reserva['hora_fin']
        
        en_rango = hora_inicio <= hora_actual <= hora_fin
        print(f"   ¿Hora actual dentro del rango? {'✅ SÍ' if en_rango else '❌ NO'}")
        print(f"   Rango: {hora_inicio} - {hora_fin}")
        print(f"   Hora actual: {hora_actual}")
    else:
        print("   ❌ No se encontró reserva para hoy")
    
    # 4. Verificar últimos accesos
    print("\n4. ÚLTIMOS ACCESOS REGISTRADOS:")
    cursor.execute("""
        SELECT al.id, al.timestamp, al.rfid_uid, al.success, u.name as usuario
        FROM access_log al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE u.name LIKE '%Alejandro%'
        ORDER BY al.timestamp DESC
        LIMIT 5
    """)
    accesos = cursor.fetchall()
    
    if accesos:
        for a in accesos:
            estado = "✅ Autorizado" if a['success'] else "❌ Denegado"
            print(f"   - {a['timestamp']} | UID: {a['rfid_uid']} | {estado}")
    else:
        print("   ❌ No hay accesos recientes")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    check_timezone()
