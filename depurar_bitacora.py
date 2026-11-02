"""
Script de depuración de la bitácora de accesos.
Sin argumentos solo informa cuántos registros superan los 24 meses de retención.
Con --aplicar los elimina de forma definitiva; ejecutar después de un respaldo.
"""
import argparse

from app import app
from control_acceso.clock import hora_actual
from control_acceso.retencion import depurar_bitacora, fecha_limite, registros_vencidos


def main(argumentos=None):
    parser = argparse.ArgumentParser(description='Depura la bitácora de accesos vencida')
    parser.add_argument('--aplicar', action='store_true', help='elimina los registros vencidos')
    opciones = parser.parse_args(argumentos)

    ahora = hora_actual()
    with app.app_context():
        if opciones.aplicar:
            print(f'Registros eliminados: {depurar_bitacora(ahora)}')
        else:
            print(f'Registros anteriores a {fecha_limite(ahora):%d/%m/%Y}: {registros_vencidos(ahora).count()}')


if __name__ == '__main__':
    main()
