from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo('America/Bogota')


def hora_actual():
    """Hora de referencia del sistema, sin zona, para compararla con las columnas DATETIME"""
    return datetime.now(ZONA_HORARIA).replace(tzinfo=None)
