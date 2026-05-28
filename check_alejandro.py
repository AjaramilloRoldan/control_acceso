"""
Script para verificar UID y reserva del usuario Alejandro
"""
import mysql.connector
import os
from dotenv import load_dotenv
from datetime import datetime

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

def check_alejandro():
    """Verifica información del usuario Alejandro"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Buscar usuario Alejandro
        print("=" * 60)
        print("BUSCANDO USUARIO ALEJANDRO")
        print("=" * 60)
        cursor.execute("SELECT id, name, rfid, username FROM users WHERE name LIKE '%Alejandro%'")
        usuario = cursor.fetchone()
        
        if not usuario:
            print("❌ No se encontró usuario con nombre 'Alejandro'")
            return
        
        print(f"✅ Usuario encontrado:")
        print(f"   ID: {usuario['id']}")
        print(f"   Nombre: {usuario['name']}")
        print(f"   Usuario: {usuario['username']}")
        print(f"   RFID: {usuario['rfid']}")
        print()
        
        # 2. Buscar reservas activas para hoy
        print("=" * 60)
        print("RESERVAS ACTIVAS PARA HOY")
        print("=" * 60)
        hoy = datetime.now().date()
        hora_actual = datetime.now().time()
        
        cursor.execute("""
            SELECT r.id, i.nombre as instalacion, r.fecha_reserva, 
                   r.hora_inicio, r.hora_fin, r.estado
            FROM reservas r
            JOIN instalaciones i ON r.instalacion_id = i.id
            WHERE r.user_id = %s AND r.fecha_reserva = %s AND r.estado = 'activa'
        """, (usuario['id'], hoy))
        
        reservas = cursor.fetchall()
        
        if not reservas:
            print(f"❌ No hay reservas activas para hoy ({hoy})")
        else:
            print(f"✅ Encontradas {len(reservas)} reserva(s) activa(s):")
            for r in reservas:
                print(f"   - ID: {r['id']}")
                print(f"     Instalación: {r['instalacion']}")
                print(f"     Fecha: {r['fecha_reserva']}")
                print(f"     Horario: {r['hora_inicio']} - {r['hora_fin']}")
                print(f"     Estado: {r['estado']}")
                print(f"     Hora actual: {hora_actual}")
                print()
        
        # 3. Mostrar últimos accesos denegados
        print("=" * 60)
        print("ÚLTIMOS ACCESOS DENEGADOS")
        print("=" * 60)
        cursor.execute("""
            SELECT al.id, al.rfid_uid, al.timestamp, u.name as usuario
            FROM access_log al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE al.success = 0
            ORDER BY al.timestamp DESC
            LIMIT 10
        """)
        
        accesos_denegados = cursor.fetchall()
        
        if not accesos_denegados:
            print("❌ No hay accesos denegados recientes")
        else:
            print(f"✅ Últimos {len(accesos_denegados)} accesos denegados:")
            for a in accesos_denegados:
                print(f"   - ID: {a['id']}")
                print(f"     UID: {a['rfid_uid']}")
                print(f"     Usuario: {a['usuario'] or 'No registrado'}")
                print(f"     Fecha: {a['timestamp']}")
                print()
        
        # 4. Comparar UIDs
        print("=" * 60)
        print("COMPARACIÓN DE UIDs")
        print("=" * 60)
        print(f"UID registrado para Alejandro: {usuario['rfid']}")
        print()
        
        if accesos_denegados:
            print("UIDs de accesos denegados recientes:")
            for a in accesos_denegados:
                match = "✅ COINCIDE" if a['rfid_uid'] == usuario['rfid'] else "❌ NO COINCIDE"
                print(f"   {a['rfid_uid']} - {match}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    check_alejandro()
