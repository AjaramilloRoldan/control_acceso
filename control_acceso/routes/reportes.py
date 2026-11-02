from datetime import date, timedelta

from flask import Blueprint, Response, render_template, request, session

from ..clock import hora_actual
from ..permisos import deny_page
from ..models import  Instalacion
from ..reports import (FILAS_EN_PANTALLA, PeriodoInvalido, reporte_bitacora, reporte_denegados, reporte_ocupacion,
                       reporte_uso, to_csv, validate_period)

bp = Blueprint('reportes', __name__)

TIPOS_REPORTE = {'ocupacion': 'Ocupación', 'uso': 'Uso', 'denegados': 'Denegados', 'bitacora': 'Bitácora'}
DIAS_POR_DEFECTO = 30

def parse_filter_date(nombre, por_defecto):
    valor = request.args.get(nombre)
    if not valor:
        return por_defecto
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise PeriodoInvalido('Fecha inválida')

def build_report(tipo, desde, hasta, instalacion_id):
    if tipo == 'ocupacion':
        return reporte_ocupacion(desde, hasta, instalacion_id)
    if tipo == 'uso':
        return reporte_uso(desde, hasta, instalacion_id)
    if tipo == 'denegados':
        return reporte_denegados(desde, hasta)
    return reporte_bitacora(desde, hasta, instalacion_id)

@bp.route('/reportes')
def reportes():
    if session.get('role') != 'admin': return deny_page()

    tipo = request.args.get('tipo', 'ocupacion')
    if tipo not in TIPOS_REPORTE:
        tipo = 'ocupacion'
    espacios = Instalacion.query.filter(Instalacion.estado != 'baja').order_by(Instalacion.nombre).all()
    instalacion_id = request.args.get('id_espacios', type=int)
    if tipo == 'ocupacion' and not instalacion_id and espacios:
        instalacion_id = espacios[0].id

    hoy = hora_actual().date()
    contexto = {'tipo': tipo, 'tipos': TIPOS_REPORTE, 'espacios': espacios, 'instalacion_id': instalacion_id,
                'fecha_desde': request.args.get('fecha_desde', ''), 'fecha_hasta': request.args.get('fecha_hasta', '')}
    try:
        desde = parse_filter_date('fecha_desde', hoy - timedelta(days=DIAS_POR_DEFECTO))
        hasta = parse_filter_date('fecha_hasta', hoy)
        validate_period(desde, hasta)
    except PeriodoInvalido as error:
        return render_template('reportes.html', error=str(error), reporte=None, **contexto), 400

    contexto.update(fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat())
    reporte = build_report(tipo, desde, hasta, instalacion_id)
    if request.args.get('formato') == 'csv':
        return Response(to_csv(reporte), content_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=reporte_{tipo}_{desde}_{hasta}.csv'})
    return render_template('reportes.html', error=None, reporte=reporte, limite_filas=FILAS_EN_PANTALLA, **contexto)
