from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, session, url_for
from sqlalchemy import func

from .. import database
from ..extensions import db, limiter
from ..metrics import ULTIMOS_ACCESOS_METRICAS, calcular_disponibilidad, percentil_95
from ..models import Instalacion, Reserva

bp = Blueprint('panel', __name__)

@bp.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM users")
    total_users = cursor.fetchone()['total']
    
    hoy = datetime.now().strftime('%Y-%m-%d')
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
        fecha_dt = (datetime.now() - timedelta(days=i))
        fecha_str = fecha_dt.strftime('%Y-%m-%d')
        labels.append(fecha_dt.strftime('%a'))
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
    
    cursor.close()
    conn.close()
    
    return jsonify({"denegados": denegados})

@bp.route('/historial')
@limiter.exempt
def historial():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))

    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT al.id, COALESCE(u.name, 'No registrado') as usuario, al.timestamp as fecha,
        CASE WHEN al.success = 1 THEN '✅ Autorizado' ELSE '❌ Denegado' END as estado
        FROM access_log al LEFT JOIN users u ON al.user_id = u.id ORDER BY al.timestamp DESC
    """)
    logs = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('historial.html', logs=logs)
