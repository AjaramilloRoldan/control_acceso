from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import Instalacion, Reserva

bp = Blueprint('reservas', __name__)

@bp.route('/instalaciones')
def instalaciones():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    lista_inst = Instalacion.query.filter_by(estado='activo').all()
    mis_reservas = Reserva.query.filter_by(user_id=session['user_id'], estado='activa').all()
    
    ahora = datetime.now()
    hora_actual = ahora.time()
    fecha_actual = ahora.date()
    
    ocupadas = [r.instalacion_id for r in Reserva.query.filter(
        Reserva.fecha_reserva == fecha_actual,
        Reserva.hora_inicio <= hora_actual,
        Reserva.hora_fin >= hora_actual,
        Reserva.estado == 'activa'
    ).all()]

    return render_template('instalaciones.html', 
                           instalaciones=lista_inst, 
                           mis_reservas=mis_reservas,
                           ocupadas=ocupadas,
                           nombre_usuario=session.get('name'))

@bp.route('/reservar', methods=['POST'])
def reservar():
    if session.get('role') != 'user': return redirect(url_for('auth.login'))
    
    inst_id = request.form.get('instalacion_id')
    instalacion = db.session.get(Instalacion, inst_id)
    if instalacion is None or instalacion.estado != 'activo':
        return "Error: Instalación no disponible", 400

    fecha = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date()
    inicio = datetime.strptime(request.form.get('hora_inicio'), '%H:%M').time()
    fin = datetime.strptime(request.form.get('hora_fin'), '%H:%M').time()

    conflicto = Reserva.query.filter(
        Reserva.instalacion_id == inst_id,
        Reserva.fecha_reserva == fecha,
        Reserva.estado == 'activa',
        db.not_(db.or_(Reserva.hora_fin <= inicio, Reserva.hora_inicio >= fin))
    ).first()

    if conflicto:
        return "Error: Horario no disponible", 400

    nueva = Reserva(user_id=session['user_id'], instalacion_id=inst_id, 
                    fecha_reserva=fecha, hora_inicio=inicio, hora_fin=fin)
    db.session.add(nueva)
    db.session.commit()
    return redirect(url_for('reservas.instalaciones'))

@bp.route('/cancelar_reserva/<int:reserva_id>', methods=['POST'])
def cancelar_reserva(reserva_id):
    reserva = Reserva.query.get_or_404(reserva_id)
    es_titular = session.get('role') == 'user' and session.get('user_id') == reserva.user_id
    if not es_titular and session.get('role') != 'admin':
        return jsonify({"error": "No autorizado"}), 403
    reserva.estado = 'cancelada'
    db.session.commit()
    return redirect(url_for('reservas.instalaciones'))

@bp.route('/api/disponibilidad/<int:inst_id>/<fecha>')
def consultar_disponibilidad(inst_id, fecha):
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    try:
        fecha_consulta = datetime.strptime(fecha, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
    reservas = Reserva.query.filter_by(instalacion_id=inst_id, fecha_reserva=fecha_consulta, estado='activa').all()
    ocupados = [{"from": r.hora_inicio.strftime('%H:%M'), "to": r.hora_fin.strftime('%H:%M')} for r in reservas]
    return jsonify(ocupados)
