from . import auth, instalaciones, lector, panel, reservas, usuarios

def register_blueprints(app):
    for module in (auth, instalaciones, lector, panel, reservas, usuarios):
        app.register_blueprint(module.bp)
