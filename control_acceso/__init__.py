import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config
from .extensions import csrf, db, limiter
from .routes import register_blueprints
from .security import configure_security_log

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://npmcdn.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com;"
    return response

def create_app():
    app = Flask(__name__, root_path=PROJECT_ROOT)
    app.secret_key = config.require_env('SECRET_KEY')
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
    app.config['SQLALCHEMY_DATABASE_URI'] = config.database_uri()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if config.behind_https_proxy():
        app.config['SESSION_COOKIE_SECURE'] = True
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    configure_security_log()

    csrf.init_app(app)
    limiter.init_app(app)
    db.init_app(app)

    app.after_request(set_security_headers)
    register_blueprints(app)
    return app
