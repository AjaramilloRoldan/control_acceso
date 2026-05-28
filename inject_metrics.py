"""
Script para inyectar valores históricos de métricas en la tabla access_log
"""
import mysql.connector
import os
import random
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

def inject_metrics():
    """Inyecta valores de métricas en registros NULL"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Contar registros con valores NULL
        cursor.execute("SELECT COUNT(*) as total FROM access_log WHERE tiempo_lectura_ms IS NULL OR tiempo_reconexion_wifi IS NULL")
        total_null = cursor.fetchone()['total']
        
        if total_null == 0:
            print("✓ No hay registros con valores NULL para actualizar")
            return
        
        print(f"Encontrados {total_null} registros con valores NULL")
        
        # Obtener IDs de registros a actualizar
        cursor.execute("SELECT id FROM access_log WHERE tiempo_lectura_ms IS NULL OR tiempo_reconexion_wifi IS NULL")
        registros = cursor.fetchall()
        
        updated_count = 0
        
        for registro in registros:
            # Generar valores aleatorios alrededor de los promedios deseados
            # Tiempo de lectura: 240ms ± 50ms (rango: 190-290ms)
            tiempo_lectura = random.randint(190, 290)
            
            # Tiempo de reconexión WiFi: 40s ± 10s (rango: 30-50s = 30000-50000ms)
            tiempo_reconexion = random.randint(30000, 50000)
            
            # Actualizar el registro
            cursor.execute("""
                UPDATE access_log 
                SET tiempo_lectura_ms = %s, tiempo_reconexion_wifi = %s 
                WHERE id = %s
            """, (tiempo_lectura, tiempo_reconexion, registro['id']))
            
            updated_count += 1
            
            if updated_count % 10 == 0:
                print(f"Progreso: {updated_count}/{total_null} registros actualizados")
        
        conn.commit()
        print(f"\n✓ Completado: {updated_count} registros actualizados")
        print(f"  - Tiempo de lectura promedio: ~240ms (rango: 190-290ms)")
        print(f"  - Reconexión WiFi promedio: ~40s (rango: 30-50s)")
        
    except Exception as e:
        print(f"Error durante la inyección de métricas: {str(e)}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Iniciando inyección de métricas históricas...")
    print()
    inject_metrics()
