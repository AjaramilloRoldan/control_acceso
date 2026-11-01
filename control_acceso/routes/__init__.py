from . import auth, instalaciones, lector, panel, reportes, reservas, usuarios

def register_blueprints(app):
    for module in (auth, instalaciones, lector, panel, reportes, reservas, usuarios):
        app.register_blueprint(module.bp)
