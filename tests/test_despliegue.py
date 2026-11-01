import gzip
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ['SECRET_KEY'] = 'test-secret'
os.environ.setdefault('DATABASE_URL', f"sqlite:///{tempfile.mkdtemp()}/test.db")

from app import app
from control_acceso import create_app
from control_acceso.extensions import limiter
import respaldar_base

DUMP_COMPLETO = "-- Dump\nCREATE TABLE `users` (id int);\n-- Dump completed on 2026-11-01\n"
AHORA = datetime(2026, 11, 1, 3, 0)


def fake_mysqldump(tmp_path, contenido, codigo=0):
    script = tmp_path / 'fake_mysqldump.py'
    script.write_text(f"import sys\nsys.stdout.write({contenido!r})\nsys.exit({codigo})\n", encoding='utf-8')
    wrapper = tmp_path / ('fake_mysqldump.cmd' if os.name == 'nt' else 'fake_mysqldump.sh')
    if os.name == 'nt':
        wrapper.write_text(f'@"{sys.executable}" "{script}"\r\n@exit /b %ERRORLEVEL%\r\n', encoding='utf-8')
    else:
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding='utf-8')
        wrapper.chmod(0o755)
    return wrapper


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    carpeta = tmp_path / 'respaldos'
    monkeypatch.setenv('BACKUP_DIR', str(carpeta))
    monkeypatch.setenv('DB_NAME', 'control_acceso')
    monkeypatch.setenv('DB_PASSWORD', 'clave-de-prueba')
    monkeypatch.setenv('BACKUP_RETENTION_DAYS', '30')
    return carpeta


def create_old_backup(carpeta, dias, nombre=None):
    carpeta.mkdir(exist_ok=True)
    fecha = AHORA - timedelta(days=dias)
    ruta = carpeta / (nombre or respaldar_base.backup_name('control_acceso', fecha))
    ruta.write_bytes(b'copia')
    os.utime(ruta, (fecha.timestamp(), fecha.timestamp()))
    return ruta


def test_backup_is_compressed_and_complete(backup_env, tmp_path, monkeypatch):
    monkeypatch.setenv('MYSQLDUMP_PATH', str(fake_mysqldump(tmp_path, DUMP_COMPLETO)))

    copia, _ = respaldar_base.backup_database(AHORA)

    assert copia.name == 'control_acceso_20261101_030000.sql.gz'
    assert gzip.decompress(copia.read_bytes()).decode().replace('\r\n', '\n') == DUMP_COMPLETO
    assert list(backup_env.glob('*.tmp')) == []


def test_truncated_dump_leaves_no_backup(backup_env, tmp_path, monkeypatch):
    monkeypatch.setenv('MYSQLDUMP_PATH', str(fake_mysqldump(tmp_path, 'CREATE TABLE `users` (id int);\n')))

    with pytest.raises(respaldar_base.RespaldoInvalido):
        respaldar_base.backup_database(AHORA)

    assert list(backup_env.iterdir()) == []


def test_failed_mysqldump_keeps_previous_backups(backup_env, tmp_path, monkeypatch):
    anterior = create_old_backup(backup_env, 90)
    monkeypatch.setenv('MYSQLDUMP_PATH', str(fake_mysqldump(tmp_path, DUMP_COMPLETO, codigo=2)))

    with pytest.raises(respaldar_base.RespaldoInvalido):
        respaldar_base.backup_database(AHORA)

    assert list(backup_env.iterdir()) == [anterior]


def test_retention_removes_only_old_automatic_backups(tmp_path):
    recientes = [create_old_backup(tmp_path, dia) for dia in range(1, 8)]
    vencida = create_old_backup(tmp_path, 31)
    manual = create_old_backup(tmp_path, 90, 'control_acceso_20260803_030000.sql')
    otra_base = create_old_backup(tmp_path, 90, 'otra_base_20260803_030000.sql.gz')

    eliminadas = respaldar_base.prune_backups(Path(tmp_path), 'control_acceso', 30, AHORA)

    assert eliminadas == [vencida]
    assert all(ruta.exists() for ruta in [*recientes, manual, otra_base])


def test_retention_never_drops_below_minimum_copies(tmp_path):
    copias = [create_old_backup(tmp_path, 100 + dia) for dia in range(7)]

    assert respaldar_base.prune_backups(Path(tmp_path), 'control_acceso', 30, AHORA) == []
    assert all(ruta.exists() for ruta in copias)


def test_app_outside_proxy_keeps_development_settings():
    assert app.config.get('SESSION_COOKIE_SECURE') is False


def test_behind_proxy_uses_secure_cookie_and_client_address(monkeypatch):
    monkeypatch.setenv('BEHIND_HTTPS_PROXY', 'True')
    proxied = create_app()
    limiter.enabled = False

    assert proxied.config['SESSION_COOKIE_SECURE'] is True

    @proxied.route('/_origen')
    def origen():
        from flask import request
        return f'{request.remote_addr} {request.scheme}'

    respuesta = proxied.test_client().get('/_origen', headers={'X-Forwarded-For': '203.0.113.9', 'X-Forwarded-Proto': 'https'})
    assert respuesta.get_data(as_text=True) == '203.0.113.9 https'
