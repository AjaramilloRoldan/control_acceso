import os

from control_acceso import create_app
from control_acceso.extensions import db

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Configuración de producción vs desarrollo
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
