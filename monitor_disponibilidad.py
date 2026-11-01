"""
Sondea /health cada 60 segundos y registra el resultado para calcular la disponibilidad.
Debe ejecutarse aparte de app.py para detectar también cuando la aplicación está caída.
"""
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HEALTH_URL = os.getenv('HEALTH_URL', 'http://127.0.0.1:5000/health')
HEALTH_LOG = 'logs/disponibilidad.log'
INTERVALO_SEGUNDOS = 60

def sondear():
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as respuesta:
            return 'ok' if respuesta.status == 200 else 'fallo'
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Sondeo fallido: {error}")
        return 'fallo'

if __name__ == "__main__":
    os.makedirs('logs', exist_ok=True)
    while True:
        marca = datetime.now(ZoneInfo('America/Bogota')).replace(tzinfo=None).isoformat(timespec='seconds')
        with open(HEALTH_LOG, 'a', encoding='utf-8') as archivo:
            archivo.write(f"{marca},{sondear()}\n")
        time.sleep(INTERVALO_SEGUNDOS)
