from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
import mysql.connector
import os
import time
from datetime import datetime, timedelta, time as dt_time
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename

# Configuración de Zona Horaria para Colombia
os.environ['TZ'] = 'America/Bogota'
if hasattr(time, 'tzset'):
    time.tzset()

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Configuración de Carga de Imágenes
UPLOAD_FOLDER = 'static/uploads/instalaciones'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- CONFIGURACIÓN DE BASE DE DATOS ---

# Conexión directa para consultas legacy (Dashboard e Historial)
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Roldan.1982",
        database="control_acceso"
    )

# Configuración SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:Roldan.1982@localhost:3306/control_acceso'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELOS ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rfid = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    reservas = db.relationship('Reserva', backref='usuario', lazy=True)

class AccessLog(db.Model):
    __tablename__ = 'access_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    success = db.Column(db.Boolean, default=True)

class Instalacion(db.Model):
    __tablename__ = 'instalaciones'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    imagen = db.Column(db.String(255), nullable=True)
    reservas = db.relationship('Reserva', backref='instalacion', lazy=True)

class Reserva(db.Model):
    __tablename__ = 'reservas'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    instalacion_id = db.Column(db.Integer, db.ForeignKey('instalaciones.id'), nullable=False)
    fecha_reserva = db.Column(db.Date, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    estado = db.Column(db.String(20), default='activa')

# --- RUTAS ADMINISTRATIVAS DE INSTALACIONES ---

@app.route('/admin_instalaciones')
def admin_instalaciones():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    todas = Instalacion.query.all()
    return render_template('admin_instalaciones.html', instalaciones=todas, admin_name=session.get('name'))

@app.route('/crear_instalacion', methods=['POST'])
def crear_instalacion():
    if session.get('role') != 'admin': return jsonify({"error": "No autorizado"}), 403
    
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')
    file = request.files.get('imagen')
    
    filename = None
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    
    nueva = Instalacion(nombre=nombre, descripcion=descripcion, imagen=filename)
    db.session.add(nueva)
    db.session.commit()
    flash('Instalación creada con éxito', 'success')
    return redirect(url_for('admin_instalaciones'))

@app.route('/editar_instalacion/<int:id>', methods=['POST'])
def editar_instalacion(id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    inst = Instalacion.query.get_or_404(id)
    
    inst.nombre = request.form.get('nombre')
    inst.descripcion = request.form.get('descripcion')
    
    file = request.files.get('imagen')
    if file and allowed_file(file.filename):
        # Eliminar imagen anterior si existe
        if inst.imagen:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], inst.imagen)
            if os.path.exists(old_path): os.remove(old_path)
            
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        inst.imagen = filename
        
    db.session.commit()
    flash('Instalación actualizada', 'success')
    return redirect(url_for('admin_instalaciones'))

@app.route('/eliminar_instalacion/<int:id>')
def eliminar_instalacion(id):
    if session.get('role') != 'admin': 
        return redirect(url_for('login'))
    
    inst = Instalacion.query.get_or_404(id)
    
    try:
        # Borrar la imagen del servidor si existe
        if inst.imagen:
            path = os.path.join(app.config['UPLOAD_FOLDER'], inst.imagen)
            if os.path.exists(path): 
                os.remove(path)
        
        # Borrar de la base de datos
        db.session.delete(inst)
        db.session.commit()

        # Lanzar el mensaje de éxito
        flash('Instalación eliminada correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error')

    return redirect(url_for('admin_instalaciones'))
    if session.get('role') != 'admin': return redirect(url_for('login'))
    inst = Instalacion.query.get_or_404(id)
    if inst.imagen:
        path = os.path.join(app.config['UPLOAD_FOLDER'], inst.imagen)
        if os.path.exists(path): os.remove(path)
    db.session.delete(inst)
    db.session.commit()
    return redirect(url_for('admin_instalaciones'))
    if session.get('role') != 'admin': return redirect(url_for('login'))
    inst = Instalacion.query.get_or_404(id)
    if inst.imagen:
        path = os.path.join(app.config['UPLOAD_FOLDER'], inst.imagen)
        if os.path.exists(path): os.remove(path)
    db.session.delete(inst)
    db.session.commit()
    flash('Instalación eliminada', 'success')
    return redirect(url_for('admin_instalaciones'))

# --- RUTAS DE NAVEGACIÓN BÁSICA ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Admin check
        cursor.execute("SELECT * FROM admin WHERE username = %s AND password = %s", (username, password))
        admin = cursor.fetchone()
        if admin:
            session.clear()
            session['user_id'] = admin['id']
            session['name'] = "Administrador"
            session['role'] = 'admin'
            cursor.close()
            conn.close()
            return redirect(url_for('dashboard'))

        # User check
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session.clear()
            session['user_id'] = user.id
            session['name'] = user.name
            session['role'] = 'user'
            return redirect(url_for('instalaciones'))
        
        cursor.close()
        conn.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- GESTIÓN DE INSTALACIONES Y RESERVAS (USUARIO) ---

@app.route('/instalaciones')
def instalaciones():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    lista_inst = Instalacion.query.all()
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

@app.route('/reservar', methods=['POST'])
def reservar():
    if session.get('role') != 'user': return redirect(url_for('login'))
    
    inst_id = request.form.get('instalacion_id')
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
    return redirect(url_for('instalaciones'))

@app.route('/cancelar_reserva/<int:reserva_id>')
def cancelar_reserva(reserva_id):
    reserva = Reserva.query.get_or_404(reserva_id)
    if session.get('user_id') == reserva.user_id or session.get('role') == 'admin':
        reserva.estado = 'cancelada'
        db.session.commit()
    return redirect(url_for('instalaciones'))

# --- PANEL ADMINISTRATIVO Y ESTADÍSTICAS ---

@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    conn = get_db()
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

@app.route('/api/stats')
def get_stats():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 401
    conn = get_db()
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

    reserva_data = db.session.query(Instalacion.nombre, func.count(Reserva.id)).join(Reserva).filter(Reserva.estado == 'activa').group_by(Instalacion.nombre).all()
    inst_names = [r[0] for r in reserva_data]
    inst_counts = [r[1] for r in reserva_data]

    eficiencia_labels = inst_names if inst_names else ["Sin Datos"]
    success_by_inst = [sum(autorizados) // (len(inst_names) or 1) for _ in eficiencia_labels]
    fail_by_inst = [sum(denegados) // (len(inst_names) or 1) for _ in eficiencia_labels]

    cursor.close()
    conn.close()
    
    return jsonify({
        "labels": labels, "autorizados": autorizados, "denegados": denegados, 
        "porcentaje_exito": porcentaje_exito, "inst_names": inst_names, "inst_counts": inst_counts,
        "eficiencia_labels": eficiencia_labels, "success_by_inst": success_by_inst, "fail_by_inst": fail_by_inst
    })

# --- GESTIÓN DE USUARIOS (CRUD) ---

@app.route('/usuarios')
def usuarios():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    usuarios_lista = User.query.all()
    return render_template('usuarios.html', usuarios=usuarios_lista)

@app.route('/agregar_usuario', methods=['POST'])
def agregar_usuario():
    if session.get('role') != 'admin': 
        return redirect(url_for('login'))

    name = request.form.get('name')
    rfid = request.form.get('rfid')
    username = request.form.get('username')
    password = request.form.get('password')

    # VALIDACIÓN
    if not all([name, rfid, username, password]):
        flash('Error: Todos los campos son obligatorios', 'error')
        return redirect(url_for('usuarios'))
    
    try:
        nuevo = User(name=name, rfid=rfid, username=username, password=password)
        db.session.add(nuevo)
        db.session.commit()
        flash('Usuario registrado con éxito', 'success')
    except:
        db.session.rollback()
        flash('Error al registrar: El UID o Usuario ya existen', 'error')
        
    return redirect(url_for('usuarios'))

@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
def editar_usuario(id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    usuario = User.query.get_or_404(id)
    
    if request.method == 'POST':
        usuario.name = request.form.get('name')
        usuario.rfid = request.form.get('rfid')
        usuario.username = request.form.get('username')
        if request.form.get('password'):
            usuario.password = request.form.get('password')
            
        try:
            db.session.commit()
            flash('Cambio aplicado correctamente', 'success') 
            return redirect(url_for('usuarios')) 
        except:
            db.session.rollback()
            flash('Error: El RFID o Usuario ya existen', 'error')
            return redirect(url_for('editar_usuario', id=id))
            
    return render_template('editar_usuario.html', usuario=usuario)

# --- Eliminar Usuario ---

@app.route('/eliminar_usuario/<int:id>', methods=['GET', 'POST'])
def eliminar_usuario(id):
    usuario_objeto = User.query.get_or_404(id) 
    
    try:
        AccessLog.query.filter_by(user_id=id).delete()
        
        db.session.delete(usuario_objeto)
        db.session.commit()
        flash('Usuario eliminado exitosamente', 'success') 
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'error') 
        
    return redirect(url_for('usuarios'))

# --- LÓGICA DE CONTROL DE ACCESO (RFID) ---

@app.route('/historial', methods=['GET', 'POST'])
def historial():
    if request.method == 'POST':
        data = request.get_json()
        uid = data.get('uid')
        inst_id = data.get('instalacion_id', 1) 
        
        user = User.query.filter_by(rfid=uid).first()
        ahora = datetime.now()
        hora_actual = ahora.time()
        fecha_actual = ahora.date()

        if not user:
            log = AccessLog(user_id=None, success=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"message": "Acceso denegado: Usuario no registrado", "access": False}), 403

        reserva = Reserva.query.filter(
            Reserva.user_id == user.id,
            Reserva.instalacion_id == inst_id,
            Reserva.fecha_reserva == fecha_actual,
            Reserva.hora_inicio <= hora_actual,
            Reserva.hora_fin >= hora_actual,
            Reserva.estado == 'activa'
        ).first()

        if reserva:
            log = AccessLog(user_id=user.id, success=True)
            db.session.add(log)
            db.session.commit()
            return jsonify({"message": f"Acceso autorizado: {user.name}", "access": True}), 200
        else:
            log = AccessLog(user_id=user.id, success=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"message": "Sin reserva activa", "access": False}), 401

    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    conn = get_db()
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

@app.route('/api/disponibilidad/<int:inst_id>/<fecha>')
def consultar_disponibilidad(inst_id, fecha):
    reservas = Reserva.query.filter_by(instalacion_id=inst_id, fecha_reserva=fecha, estado='activa').all()
    ocupados = [{"from": r.hora_inicio.strftime('%H:%M'), "to": r.hora_fin.strftime('%H:%M')} for r in reservas]
    return jsonify(ocupados)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')