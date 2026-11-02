import time

import mysql.connector
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError

from .. import config, database
from ..extensions import limiter
from ..models import VERSION_AVISO, User
from ..security import log_security_event, verify_password

bp = Blueprint('auth', __name__)

def start_session(user_id, name, role):
    session.clear()
    session.permanent = True
    session['user_id'] = user_id
    session['name'] = name
    session['role'] = role
    session['expira_en'] = time.time() + config.DURACION_SESION.total_seconds()

@bp.before_app_request
def expire_session():
    if session.get('expira_en', float('inf')) < time.time():
        session.clear()

def find_admin(username):
    conn = database.get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM admin WHERE username = %s", (username,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes", methods=['POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    username = request.form.get('username', '')
    password = request.form.get('password', '')
    client_ip = request.remote_addr

    try:
        admin = find_admin(username)
        user = User.query.filter((User.username == username) | (User.email == username)).first()
    except (mysql.connector.Error, SQLAlchemyError):
        current_app.logger.exception('Base de datos no disponible durante el inicio de sesión')
        flash('Servicio no disponible. Intenta de nuevo más tarde.', 'error')
        return render_template('login.html'), 503

    if admin and verify_password(password, admin['password']):
        start_session(admin['id'], "Administrador", 'admin')
        log_security_event('LOGIN_SUCCESS', user_id=admin['id'], details='Admin login', ip=client_ip)
        return redirect(url_for('panel.dashboard'))

    if user and user.estado == 'activo' and verify_password(password, user.password):
        start_session(user.id, user.name, 'user')
        log_security_event('LOGIN_SUCCESS', user_id=user.id, details='User login', ip=client_ip)
        if user.version_aviso != VERSION_AVISO:
            session['aviso_pendiente'] = True
            return redirect(url_for('usuarios.autorizacion'))
        return redirect(url_for('reservas.instalaciones'))

    log_security_event('LOGIN_FAILED', details=f'Username: {username}', ip=client_ip)
    flash('Credenciales inválidas', 'error')
    return render_template('login.html'), 401

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.index'))
