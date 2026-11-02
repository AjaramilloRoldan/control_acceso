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

`SECRET_KEY` y `DB_PASSWORD` son obligatorias: la aplicación no inicia sin ellas.

### 3. Generar Secret Key

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Cada lector tiene su propio token. Para registrarlo:

```bash
python registrar_dispositivo.py 2 "Lector principal"
```

Para el firmware, copiar `EjecutableHardware/secrets.example.h` como `EjecutableHardware/secrets.h` y usar ese token.

### 4. Migrar Contraseñas Existentes

Si tienes administradores o usuarios con contraseñas en texto plano, ejecuta:

```bash
python migrate_passwords.py
```

**IMPORTANTE:** Haz backup de tu base de datos antes de migrar.

Para instalaciones existentes, agregar también el modelo de datos y las columnas de reservas:

```bash
python migrate_modelo.py
python migrate_reservas.py
python migrate_notificaciones.py
python migrate_capacidad.py
```

### 5. Ejecutar la Aplicación

```bash
python app.py
```

### 6. Medir la Disponibilidad

En otra terminal, junto a `app.py`:

```bash
python monitor_disponibilidad.py
```

El panel muestra `--` en las métricas sin datos. Tiempo de lectura y reconexión WiFi solo usan accesos registrados con `instalacion_id` (`python migrate_metricas.py` agrega la columna); los registros anteriores se conservan, pero no entran en esos cálculos.

## Configuración de Producción

El sistema se despliega en Linux con Gunicorn detrás de Nginx, que termina TLS 1.2 o superior. `python app.py` es solo para desarrollo.

1. Copiar el proyecto en `/opt/control_acceso`, crear `venv` e instalar `requirements.txt`
2. En `.env`: `FLASK_DEBUG=False`, un `SECRET_KEY` fuerte y `BEHIND_HTTPS_PROXY=True`
3. Ejecutar los scripts `migrate_*.py`
4. Instalar `deploy/control-acceso.service` en `/etc/systemd/system/` y activarlo con `systemctl enable --now control-acceso`
5. Copiar `deploy/nginx.conf.example` a la configuración de Nginx, cambiar el dominio y obtener el certificado con Certbot
6. Abrir solo los puertos 80 y 443 en el firewall
7. Para el monitor de disponibilidad, usar `HEALTH_URL=http://127.0.0.1:8000/health`
8. Revisar logs de seguridad regularmente

Con `BEHIND_HTTPS_PROXY=True` la aplicación confía en las cabeceras `X-Forwarded-*` de un proxy, así que Gunicorn no debe quedar expuesto directamente: escucha solo en `127.0.0.1:8000`.

Nginx redirige todo el tráfico a HTTPS. Antes de activarlo, el firmware del ESP32 debe usar `https://` con el certificado raíz; con la versión actual, que usa `http://`, los lectores dejarían de funcionar.

### Lectores

En `/dispositivos` el administrador registra un lector y recibe su token una sola vez; va en `DEVICE_TOKEN` de `secrets.h`. El firmware debe usar como `INSTALACION_ID` el valor que muestra esa pantalla. Desde ahí también se revoca: el lector recibe 401 desde su siguiente lectura. `registrar_dispositivo.py` hace el registro por consola.

### Autorización de Datos

Cada usuario debe aceptar el aviso de privacidad en su primer inicio de sesión. Sin esa autorización no entra a la plataforma y el lector lo deniega con `SIN_AUTORIZACION_DATOS`, aunque tenga reserva. Los usuarios ya registrados también deben aceptarlo antes de volver a abrir una puerta.

El texto está en `templates/autorizacion.html`. Al publicar un cambio, subir `VERSION_AVISO` en `control_acceso/models.py`: se pedirá de nuevo la aceptación en el siguiente inicio de sesión, sin bloquear las tarjetas mientras tanto.

### Respaldos

`python respaldar_base.py` crea una copia comprimida en `BACKUP_DIR`, comprueba que esté completa y borra las copias automáticas con más de `BACKUP_RETENTION_DAYS` días, conservando siempre las 7 más recientes. Si falla, termina con código 1 y no toca las copias anteriores.

Programarlo una vez al día para cumplir el RPO de 24 horas. En Linux, con `crontab -e`:

```
0 3 * * * cd /opt/control_acceso && venv/bin/python respaldar_base.py >> logs/respaldos.log 2>&1
```

Guardar `BACKUP_DIR` fuera del disco del servidor: una copia en el mismo disco no protege si ese disco falla.

Para restaurar, primero en una base de prueba:

```bash
mysql -u root -p -e "CREATE DATABASE control_acceso_prueba"
gunzip -c control_acceso_AAAAMMDD_HHMMSS.sql.gz | mysql -u root -p control_acceso_prueba
```

Hacer este simulacro cada trimestre y comparar los conteos de filas con la base real.

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
- gunicorn 23.0.0

## Estructura del Proyecto

```
control_acceso/
├── app.py                      # Punto de entrada
├── control_acceso/             # Paquete de la aplicación
│   ├── __init__.py             # create_app y cabeceras de seguridad
│   ├── config.py               # Variables de entorno
│   ├── clock.py                # Hora de referencia (America/Bogota)
│   ├── database.py             # Conexión directa a MySQL
│   ├── extensions.py           # SQLAlchemy, CSRF y rate limiting
│   ├── models.py               # Modelos de datos
│   ├── access.py               # Reglas de autorización de acceso
│   ├── reservations.py         # Reglas de reservas y programación recurrente
│   ├── notifications.py        # Bandeja y correo de notificaciones
│   ├── reports.py              # Reportes y exportación CSV
│   ├── metrics.py              # Cálculo de métricas
│   ├── security.py             # Contraseñas, tokens y log de seguridad
│   ├── validators.py           # Validación de inputs
│   └── routes/                 # Rutas por área (blueprints)
├── deploy/                     # Gunicorn, systemd y Nginx para producción
├── registrar_dispositivo.py    # Registro de lectores por consola
├── respaldar_base.py           # Respaldo diario con retención
├── migrate_capacidad.py        # Agrega capacidad y nombre único a los espacios
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
