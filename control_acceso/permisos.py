from flask import jsonify, redirect, render_template, request, session, url_for

from .security import log_security_event

def log_denied_access():
    log_security_event('ACCESS_DENIED', user_id=session['user_id'],
                       details=f"Rol: {session.get('role')}; ruta: {request.method} {request.path}",
                       ip=request.remote_addr)

def deny_page():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    log_denied_access()
    return render_template('403.html'), 403

def deny_json():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    log_denied_access()
    return jsonify({"error": "Forbidden"}), 403
