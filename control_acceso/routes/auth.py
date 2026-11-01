from flask import Blueprint, redirect, render_template, request, session, url_for

from .. import database
from ..extensions import limiter
from ..models import VERSION_AVISO, User
from ..security import log_security_event, verify_password

bp = Blueprint('auth', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes", methods=['POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        client_ip = request.remote_addr
        
        conn = database.get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM admin WHERE username = %s", (username,))
        admin = cursor.fetchone()
        if admin and verify_password(password, admin['password']):
            session.clear()
            session['user_id'] = admin['id']
            session['name'] = "Administrador"
            session['role'] = 'admin'
            cursor.close()
            conn.close()
            log_security_event('LOGIN_SUCCESS', user_id=admin['id'], details='Admin login', ip=client_ip)
            return redirect(url_for('panel.dashboard'))

        # User check con bcrypt
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        if user and user.estado == 'activo' and verify_password(password, user.password):
            session.clear()
            session['user_id'] = user.id
            session['name'] = user.name
            session['role'] = 'user'
            cursor.close()
            conn.close()
            log_security_event('LOGIN_SUCCESS', user_id=user.id, details='User login', ip=client_ip)
            if user.version_aviso != VERSION_AVISO:
                session['aviso_pendiente'] = True
                return redirect(url_for('usuarios.autorizacion'))
            return redirect(url_for('reservas.instalaciones'))
        
        # Login fallido
        log_security_event('LOGIN_FAILED', details=f'Username: {username}', ip=client_ip)
        cursor.close()
        conn.close()
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.index'))
