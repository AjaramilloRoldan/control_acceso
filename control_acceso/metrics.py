import logging
import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

HEALTH_LOG = 'logs/disponibilidad.log'
TIEMPO_LECTURA_MAXIMO_MS = 60000
ULTIMOS_ACCESOS_METRICAS = 100

def percentil_95(valores):
    """Percentil 95 por rango más cercano"""
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[math.ceil(0.95 * len(ordenados)) - 1]

def calcular_disponibilidad(ruta=HEALTH_LOG, dias=30, ahora=None):
    """Porcentaje de sondeos exitosos de /health en horario lunes a sábado de 06:00 a 22:00"""
    if not os.path.exists(ruta):
        return None
    ahora = ahora or datetime.now(ZoneInfo('America/Bogota')).replace(tzinfo=None)
    limite = ahora - timedelta(days=dias)
    exitosos = total = 0
    with open(ruta, encoding='utf-8') as archivo:
        for linea in archivo:
            try:
                marca, estado = linea.strip().split(',')
                momento = datetime.fromisoformat(marca)
            except ValueError:
                logger.warning('Línea inválida en %s: %r', ruta, linea)
                continue
            if momento < limite or momento.weekday() == 6 or not 6 <= momento.hour < 22:
                continue
            total += 1
            exitosos += estado == 'ok'
    return round(exitosos / total * 100, 2) if total else None
