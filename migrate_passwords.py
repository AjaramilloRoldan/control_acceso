"""
Script de migración de contraseñas a bcrypt
Este script convierte contraseñas en texto plano a hashes bcrypt
"""
import mysql.connector
import bcrypt
import os
from dotenv import load_dotenv

# Cargar variables de entorno1
load_dotenv()

def get_db():
    """Conexión a la base de datos"""
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', 'Roldan.1982'),
        database=os.getenv('DB_NAME', 'control_acceso')
    )

def hash_password(password):
    """Hashea una contraseña usando bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def is_bcrypt_hash(password):
    """Verifica si una cadena es un hash bcrypt"""
    try:
        # Los hashes bcrypt tienen longitud de 60 caracteres y empiezan con $2b$, $2a$, etc.
        return len(password) == 60 and password.startswith('$2')
    except:
        return False

def migrate_passwords():
    """Migra contraseñas de texto plano a bcrypt"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Obtener todos los usuarios
        cursor.execute("SELECT id, username, password FROM users")
        users = cursor.fetchall()
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        print(f"Total de usuarios encontrados: {len(users)}")
        print("-" * 50)
        
        for user in users:
            user_id = user['id']
            username = user['username']
            current_password = user['password']
            
            # Verificar si ya está en formato bcrypt
            if is_bcrypt_hash(current_password):
                print(f"✓ Usuario {username} (ID: {user_id}) - Ya tiene contraseña encriptada")
                skipped_count += 1
                continue
            
            # Migrar a bcrypt
            try:
                hashed_password = hash_password(current_password)
                
                # Actualizar en la base de datos
                update_query = "UPDATE users SET password = %s WHERE id = %s"
                cursor.execute(update_query, (hashed_password, user_id))
                conn.commit()
                
                print(f"✓ Usuario {username} (ID: {user_id}) - Migrado exitosamente")
                migrated_count += 1
                
            except Exception as e:
                print(f"✗ Error migrando usuario {username} (ID: {user_id}): {str(e)}")
                error_count += 1
                conn.rollback()
        
        print("-" * 50)
        print(f"Migración completada:")
        print(f"  - Migrados exitosamente: {migrated_count}")
        print(f"  - Ya estaban encriptados: {skipped_count}")
        print(f"  - Errores: {error_count}")
        print(f"  - Total procesados: {len(users)}")
        
    except Exception as e:
        print(f"Error durante la migración: {str(e)}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Iniciando migración de contraseñas a bcrypt...")
    print("ADVERTENCIA: Este proceso modificará las contraseñas en la base de datos.")
    print("Asegúrese de tener un backup antes de continuar.")
    print()
    
    confirm = input("¿Desea continuar? (s/n): ")
    if confirm.lower() == 's':
        migrate_passwords()
    else:
        print("Migración cancelada.")
