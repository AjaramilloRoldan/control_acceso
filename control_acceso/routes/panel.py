from datetime import timedelta

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from .. import database
from ..clock import hora_actual
from ..extensions import db, limiter
from ..metrics import ULTIMOS_ACCESOS_METRICAS, calcular_disponibilidad, percentil_95
from ..formatos import DIAS_SEMANA, fecha_hora_local
from ..models import AccessLog, Dispositivo, Instalacion, Reserva, User
from ..reports import FILAS_POR_PAGINA, PeriodoInvalido, consulta_bitacora, reporte_consulta_bitacora, to_csv
from .reportes import parse_filter_date

bp = Blueprint('panel', __name__)

ACCESOS_EN_PANEL = 10

@bp.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE estado = 'activo'")
    total_users = cursor.fetchone()['total']
    
    hoy = hora_actual().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*) as hoy FROM access_log WHERE DATE(timestamp) = %s", (hoy,))
    accesos_hoy = cursor.fetchone()['hoy']

    cursor.execute("SELECT COUNT(*) as fallas FROM access_log WHERE DATE(timestamp) = %s AND success = 0", (hoy,))
    denegados_hoy = cursor.fetchone()['fallas']
    
    reservas_activas = Reserva.query.filter_by(estado='activa').count()
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', 
                            admin_name=session.get('name'), 
                            total_users=total_users, 
                            accesos_hoy=accesos_hoy,
                            denegados_hoy=denegados_hoy,
                            reservas_pendientes=reservas_activas)

@bp.route('/api/stats')
def get_stats():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 401
    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    labels, autorizados, denegados = [], [], []
    
    for i in range(6, -1, -1):
        fecha_dt = (hora_actual() - timedelta(days=i))
        fecha_str = fecha_dt.strftime('%Y-%m-%d')
        labels.append(DIAS_SEMANA[fecha_dt.weekday()])
        cursor.execute("SELECT COUNT(*) as c FROM access_log WHERE DATE(timestamp) = %s AND success = 1", (fecha_str,))
        autorizados.append(cursor.fetchone()['c'])
        cursor.execute("SELECT COUNT(*) as c FROM access_log WHERE DATE(timestamp) = %s AND success = 0", (fecha_str,))
        denegados.append(cursor.fetchone()['c'])

    cursor.execute("SELECT COUNT(*) as total FROM access_log")
    total = cursor.fetchone()['total'] or 1
    cursor.execute("SELECT COUNT(*) as ok FROM access_log WHERE success = 1")
    porcentaje_exito = round((cursor.fetchone()['ok'] / total) * 100, 1)

    # Solo registros del firmware que mide correctamente (identificados por instalacion_id)
    cursor.execute("""
        SELECT tiempo_lectura_ms FROM access_log
        WHERE instalacion_id IS NOT NULL AND tiempo_lectura_ms IS NOT NULL
        ORDER BY timestamp DESC LIMIT %s
    """, (ULTIMOS_ACCESOS_METRICAS,))
    tiempos_lectura = [fila['tiempo_lectura_ms'] for fila in cursor.fetchall()]
    tiempo_lectura_promedio = round(sum(tiempos_lectura) / len(tiempos_lectura)) if tiempos_lectura else None

    cursor.execute("""
        SELECT AVG(tiempo_reconexion_wifi) as avg_reconexion FROM access_log
        WHERE instalacion_id IS NOT NULL AND tiempo_reconexion_wifi > 0
    """)
    avg_reconexion = cursor.fetchone()['avg_reconexion']
    tiempo_reconexion_promedio = round(avg_reconexion) if avg_reconexion is not None else None

    cursor.execute("""
        SELECT i.nombre, SUM(al.success = 1) as exitos, SUM(al.success = 0) as fallas
        FROM access_log al JOIN instalaciones i ON al.instalacion_id = i.id
        GROUP BY i.nombre ORDER BY i.nombre
    """)
    eficiencia = cursor.fetchall()

    reserva_data = db.session.query(Instalacion.nombre, func.count(Reserva.id)).join(Reserva).filter(Reserva.estado == 'activa').group_by(Instalacion.nombre).all()
    inst_names = [r[0] for r in reserva_data]
    inst_counts = [r[1] for r in reserva_data]

    cursor.close()
    conn.close()
    
    return jsonify({
        "labels": labels, "autorizados": autorizados, "denegados": denegados, 
        "porcentaje_exito": porcentaje_exito, "inst_names": inst_names, "inst_counts": inst_counts,
        "eficiencia_labels": [fila['nombre'] for fila in eficiencia],
        "success_by_inst": [int(fila['exitos']) for fila in eficiencia],
        "fail_by_inst": [int(fila['fallas']) for fila in eficiencia],
        "tiempo_lectura_promedio": tiempo_lectura_promedio,
        "tiempo_lectura_p95": percentil_95(tiempos_lectura),
        "disponibilidad": calcular_disponibilidad(),
        "tiempo_reconexion_wifi": tiempo_reconexion_promedio
    })

@bp.route('/api/denegados')
def get_denegados():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 401
    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT al.id, al.rfid_uid, al.timestamp as fecha,
        CASE WHEN al.user_id IS NULL THEN 'Usuario no registrado' 
             ELSE u.name END as usuario
        FROM access_log al 
        LEFT JOIN users u ON al.user_id = u.id 
        WHERE al.success = 0 AND al.rfid_uid IS NOT NULL
        ORDER BY al.timestamp DESC 
        LIMIT 50
    """)
    denegados = cursor.fetchall()
    for denegado in denegados:
        denegado['fecha'] = fecha_hora_local(denegado['fecha'])

    cursor.close()
    conn.close()
    
    return jsonify({"denegados": denegados})

def filas_de_acceso(registros):
    return [{'fecha': fecha_hora_local(acceso.timestamp), 'usuario': usuario or 'No registrado',
             'espacio': espacio or 'Sin espacio', 'autorizado': acceso.success, 'motivo': acceso.motivo or ''}
            for acceso, usuario, espacio in registros]

@bp.route('/api/monitoreo')
@limiter.exempt
def monitoreo():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 401

    ahora = hora_actual()
    conteo = dict(db.session.query(AccessLog.success, func.count(AccessLog.id))
                  .filter(AccessLog.timestamp >= ahora.replace(hour=0, minute=0, second=0, microsecond=0)).group_by(AccessLog.success).all())
    reservas = db.session.query(Reserva, User.name, Instalacion.nombre) \
        .join(User, Reserva.user_id == User.id).join(Instalacion, Reserva.instalacion_id == Instalacion.id) \
        .filter(Reserva.fecha_reserva == ahora.date(), Reserva.estado == 'activa').order_by(Reserva.hora_inicio).all()
    lectores = db.session.query(Dispositivo, Instalacion.nombre) \
        .join(Instalacion, Dispositivo.instalacion_id == Instalacion.id) \
        .filter(Dispositivo.estado == 'activo').order_by(Instalacion.nombre).all()

    return jsonify({
        "autorizados_hoy": conteo.get(True, 0),
        "denegados_hoy": conteo.get(False, 0),
        "ultimos_accesos": filas_de_acceso(consulta_bitacora().limit(ACCESOS_EN_PANEL).all()),
        "reservas_hoy": [{'franja': f"{reserva.hora_inicio.strftime('%H:%M')} - {reserva.hora_fin.strftime('%H:%M')}",
                          'usuario': usuario, 'espacio': espacio} for reserva, usuario, espacio in reservas],
        "dispositivos": [{'descripcion': lector.descripcion or 'Sin descripción', 'espacio': espacio,
                          'ultima_conexion': fecha_hora_local(lector.ultima_conexion) if lector.ultima_conexion else None}
                         for lector, espacio in lectores],
    })

@bp.route('/historial')
@limiter.exempt
def historial():
    rol = session.get('role')
    if rol not in ('admin', 'user'): return redirect(url_for('auth.login'))

    usuario_id = request.args.get('id_usuario', type=int)
    if rol == 'user':
        if usuario_id not in (None, session['user_id']):
            abort(403)
        usuario_id = session['user_id']

    filtros = {clave: valor for clave, valor in request.args.items() if valor and clave not in ('pagina', 'formato')}
    contexto = {'es_admin': rol == 'admin', 'filtros': filtros, 'espacios': Instalacion.query.order_by(Instalacion.nombre).all(),
                'motivos': [fila[0] for fila in db.session.query(AccessLog.motivo).filter(AccessLog.motivo.isnot(None)).distinct().order_by(AccessLog.motivo)],
                'usuarios': User.query.order_by(User.name).all() if rol == 'admin' else []}
    try:
        desde = parse_filter_date('fecha_desde', None)
        hasta = parse_filter_date('fecha_hasta', None)
        if desde and hasta and desde > hasta:
            raise PeriodoInvalido('La fecha inicial es posterior a la final')
    except PeriodoInvalido as error:
        return render_template('historial.html', error=str(error), logs=[], paginacion=None, **contexto), 400

    consulta = consulta_bitacora(desde, hasta, request.args.get('id_espacios', type=int), usuario_id,
                                 request.args.get('resultado'), request.args.get('motivo') or None)
    if request.args.get('formato') == 'csv':
        return Response(to_csv(reporte_consulta_bitacora(consulta)), content_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename=bitacora.csv'})

    paginacion = consulta.paginate(page=request.args.get('pagina', 1, type=int), per_page=FILAS_POR_PAGINA, error_out=False)
    return render_template('historial.html', error=None, logs=filas_de_acceso(paginacion.items), paginacion=paginacion, **contexto)
