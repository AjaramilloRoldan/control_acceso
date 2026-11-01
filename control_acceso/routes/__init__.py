from . import auth, dispositivos, instalaciones, lector, panel, reportes, reservas, usuarios

def register_blueprints(app):
    for module in (auth, dispositivos, instalaciones, lector, panel, reportes, reservas, usuarios):
        app.register_blueprint(module.bp)
