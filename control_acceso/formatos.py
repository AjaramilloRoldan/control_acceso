"""Formatos locales de la interfaz y los reportes (RNF-CS-22)"""

DIAS_SEMANA = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')


def fecha_local(valor):
    return valor.strftime('%d/%m/%Y')


def fecha_hora_local(valor, segundos=True):
    return valor.strftime('%d/%m/%Y %H:%M:%S' if segundos else '%d/%m/%Y %H:%M')
