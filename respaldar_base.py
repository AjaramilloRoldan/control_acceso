"""
Script de respaldo de la base de datos.
Genera una copia comprimida con mysqldump, comprueba que esté completa y
elimina las copias automáticas que superan la retención.
Pensado para ejecutarse una vez al día (RPO de 24 horas).
"""
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

MIN_COPIES_TO_KEEP = 7
TAIL_BYTES = 4096


class RespaldoInvalido(Exception):
    pass


def backup_name(db_name, ahora):
    return f"{db_name}_{ahora.strftime('%Y%m%d_%H%M%S')}.sql.gz"


def run_mysqldump(destino):
    db_name = os.getenv('DB_NAME', 'control_acceso')
    command = [
        os.getenv('MYSQLDUMP_PATH', 'mysqldump'),
        '-h', os.getenv('DB_HOST', 'localhost'),
        '-u', os.getenv('DB_USER', 'root'),
        '--single-transaction', '--routines', '--triggers', db_name,
    ]
    env = {**os.environ, 'MYSQL_PWD': os.environ['DB_PASSWORD']}
    with gzip.open(destino, 'wb') as salida:
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE) as proceso:
            shutil.copyfileobj(proceso.stdout, salida)
    if proceso.returncode != 0:
        raise RespaldoInvalido(f'mysqldump terminó con código {proceso.returncode}')


def verify_backup(ruta):
    cola = b''
    tiene_tablas = False
    with gzip.open(ruta, 'rb') as copia:
        while bloque := copia.read(1024 * 1024):
            tiene_tablas = tiene_tablas or b'CREATE TABLE' in bloque
            cola = (cola + bloque)[-TAIL_BYTES:]
    if not tiene_tablas or b'Dump completed' not in cola:
        raise RespaldoInvalido(f'La copia {ruta} está incompleta')


def prune_backups(carpeta, db_name, dias, ahora):
    limite = ahora - timedelta(days=dias)
    copias = sorted(carpeta.glob(f'{db_name}_*.sql.gz'), key=lambda ruta: ruta.stat().st_mtime, reverse=True)
    eliminadas = []
    for copia in copias[MIN_COPIES_TO_KEEP:]:
        if datetime.fromtimestamp(copia.stat().st_mtime) < limite:
            copia.unlink()
            eliminadas.append(copia)
    return eliminadas


def backup_database(ahora=None):
    ahora = ahora or datetime.now()
    carpeta = Path(os.environ['BACKUP_DIR'])
    carpeta.mkdir(parents=True, exist_ok=True)
    db_name = os.getenv('DB_NAME', 'control_acceso')

    destino = carpeta / backup_name(db_name, ahora)
    temporal = destino.with_suffix('.tmp')
    try:
        temporal.touch(mode=0o600)
        run_mysqldump(temporal)
        verify_backup(temporal)
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)

    eliminadas = prune_backups(carpeta, db_name, int(os.getenv('BACKUP_RETENTION_DAYS', '30')), ahora)
    return destino, eliminadas


if __name__ == '__main__':
    try:
        copia, eliminadas = backup_database()
    except (RespaldoInvalido, KeyError, OSError) as error:
        print(f'Respaldo fallido: {error!r}', file=sys.stderr)
        sys.exit(1)
    print(f'Respaldo creado: {copia} ({copia.stat().st_size} bytes); copias antiguas eliminadas: {len(eliminadas)}')
