# Sistema de Control de Acceso - Seguridad

Sistema de control de acceso para instalaciones privadas con medidas de seguridad estándar implementadas.

## Características de Seguridad

### 1. Encriptación de Contraseñas (bcrypt)
- Todas las contraseñas se almacenan hasheadas con bcrypt
- Longitud de columna aumentada a 255 caracteres para hashes bcrypt
- Funciones de hash y verificación implementadas

### 2. Variables de Entorno
- Credenciales sensibles almacenadas en variables de entorno
- Archivo `.env.example` como plantilla de configuración
- `.env` incluido en `.gitignore` para proteger secretos

### 3. Protección CSRF
- Tokens CSRF en todos los formularios
- Flask-WTF configurado para protección automática

### 4. Rate Limiting
- Límite de 5 intentos de login cada 15 minutos por IP
- Límites globales: 200 por día, 50 por hora
- Protección contra ataques de fuerza bruta

### 5. Logging de Seguridad
- Logs de eventos de seguridad en `logs/security.log`
- Rotación automática de logs (1MB máximo, 5 backups)
- Eventos registrados: login exitoso/fallido, creación/actualización de usuarios

### 6. Headers de Seguridad HTTP
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Strict-Transport-Security: max-age=31536000
- Content-Security-Policy configurado

### 7. Configuración de Producción
- Debug mode deshabilitado por defecto
- Configuración separada para desarrollo y producción
- Controlado por variable de entorno `FLASK_DEBUG`

### 8. Validación de Inputs
- Validación de username (3-50 caracteres, alfanuméricos y guiones bajos)
- Validación de contraseña (mínimo 6 caracteres)
- Validación de nombre (2-100 caracteres)
- Validación de RFID (3-50 caracteres)

## Instalación

### 1. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 2. Configurar Variables de Entorno
Crear archivo `.env` basado en `.env.example`:
```bash
cp .env.example .env
```

Editar `.env` con tus credenciales:
```
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=tu_contraseña
DB_NAME=control_acceso
SECRET_KEY=generar_con_python_secrets
FLASK_ENV=development
FLASK_DEBUG=True
```

### 3. Generar Secret Key
```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

### 4. Migrar Contraseñas Existentes
Si tienes usuarios con contraseñas en texto plano, ejecuta:
```bash
python migrate_passwords.py
```

**IMPORTANTE:** Haz backup de tu base de datos antes de migrar.

### 5. Ejecutar la Aplicación
```bash
python app.py
```

## Configuración de Producción

Para desplegar en producción:

1. Establecer `FLASK_DEBUG=False` en `.env`
2. Generar un SECRET_KEY fuerte
3. Usar HTTPS (recomendado)
4. Configurar firewall apropiadamente
5. Revisar logs de seguridad regularmente

## Logs de Seguridad

Los logs de seguridad se almacenan en `logs/security.log`:
- Eventos de login (exitosos y fallidos)
- Creación de usuarios
- Actualización de usuarios
- Incluyen: timestamp, tipo de evento, user ID, detalles, IP

## Dependencias

- Flask 3.0.0
- Flask-SQLAlchemy 3.1.1
- mysql-connector-python 8.2.0
- python-dotenv 1.0.0
- bcrypt 4.1.2
- flask-wtf 1.2.1
- flask-limiter 3.5.0
- Werkzeug 3.0.1

## Estructura del Proyecto

```
control_acceso/
├── app.py                      # Aplicación principal con seguridad
├── migrate_passwords.py        # Script de migración de contraseñas
├── requirements.txt            # Dependencias
├── .env.example               # Plantilla de configuración
├── .gitignore                 # Archivos ignorados por git
├── logs/                      # Logs de seguridad (ignorado por git)
├── static/                    # Archivos estáticos
├── templates/                 # Templates HTML con CSRF tokens
└── control_acceso.mwb         # Esquema de base de datos
```

## Normas de Seguridad Cumplidas

- Encriptación de datos sensibles (contraseñas)
- Protección contra inyección SQL (parameterized queries)
- Protección CSRF
- Rate limiting
- Logging de auditoría
- Headers de seguridad
- Validación de inputs
- Separación de configuración sensible

## Soporte

Para problemas técnicos o preguntas de seguridad, revisa los logs en `logs/security.log`.
