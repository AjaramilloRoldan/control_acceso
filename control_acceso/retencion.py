"""Retención de la bitácora de accesos durante 24 meses (RNF-CS-17)"""
from .extensions import db
from .models import AccessLog
from .security import log_security_event

ANIOS_RETENCION = 2


def fecha_limite(ahora):
    try:
        return ahora.replace(year=ahora.year - ANIOS_RETENCION)
    except ValueError:
        return ahora.replace(year=ahora.year - ANIOS_RETENCION, day=28)


def registros_vencidos(ahora):
    return AccessLog.query.filter(AccessLog.timestamp < fecha_limite(ahora))


def depurar_bitacora(ahora):
    eliminados = registros_vencidos(ahora).delete(synchronize_session=False)
    db.session.commit()
    log_security_event('BITACORA_DEPURADA', details=f'Registros eliminados: {eliminados}')
    return eliminados
