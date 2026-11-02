from datetime import datetime

from .clock import hora_actual
from .extensions import db

ROLES_USUARIO = ('estudiante', 'docente', 'administrativo')
MOTIVOS_REVOCACION = ('perdida', 'deterioro', 'retiro')
VERSION_AVISO = '1.0'

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(45), nullable=True)
    identificacion = db.Column(db.String(45), unique=True, nullable=True)
    email = db.Column(db.String(200), unique=True, nullable=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # Aumentado para bcrypt
    rol = db.Column(db.String(20), nullable=False, default='estudiante')
    estado = db.Column(db.String(10), nullable=False, default='activo')
    autorizacion_datos = db.Column(db.DateTime, nullable=True)
    version_aviso = db.Column(db.String(10), nullable=True)
    reservas = db.relationship('Reserva', backref='usuario', lazy=True)
    tarjetas = db.relationship('Tarjeta', backref='usuario', lazy=True)

    @property
    def tarjeta_activa(self):
        return next((tarjeta for tarjeta in self.tarjetas if tarjeta.estado == 'activa'), None)

    @property
    def rfid(self):
        return self.tarjeta_activa.uid if self.tarjeta_activa else ''

class Tarjeta(db.Model):
    __tablename__ = 'tarjetas'
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    estado = db.Column(db.String(10), nullable=False, default='activa')
    motivo_revocacion = db.Column(db.String(20), nullable=True)
    fecha_asignacion = db.Column(db.DateTime, nullable=False, default=hora_actual)
    fecha_revocacion = db.Column(db.DateTime, nullable=True)

class Dispositivo(db.Model):
    __tablename__ = 'dispositivos'
    id = db.Column(db.Integer, primary_key=True)
    instalacion_id = db.Column(db.Integer, db.ForeignKey('instalaciones.id'), nullable=False)
    descripcion = db.Column(db.String(100), nullable=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    estado = db.Column(db.String(10), nullable=False, default='activo')
    ultima_conexion = db.Column(db.DateTime, nullable=True)

class AccessLog(db.Model):
    __tablename__ = 'access_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rfid_uid = db.Column(db.String(50), nullable=True)
    instalacion_id = db.Column(db.Integer, db.ForeignKey('instalaciones.id', ondelete='SET NULL'), nullable=True)
    dispositivo_id = db.Column(db.Integer, db.ForeignKey('dispositivos.id', ondelete='SET NULL'), nullable=True)
    timestamp = db.Column(db.DateTime, default=hora_actual)
    success = db.Column(db.Boolean, default=True)
    motivo = db.Column(db.String(45), nullable=True)
    tiempo_lectura_ms = db.Column(db.Integer, nullable=True)
    tiempo_reconexion_wifi = db.Column(db.Integer, nullable=True)

class Instalacion(db.Model):
    __tablename__ = 'instalaciones'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    imagen = db.Column(db.String(255), nullable=True)
    ubicacion = db.Column(db.String(45), nullable=True)
    capacidad = db.Column(db.Integer, nullable=True)
    dotacion = db.Column(db.String(255), nullable=True)
    estado = db.Column(db.String(20), nullable=False, default='activo')
    roles_permitidos = db.Column(db.String(100), nullable=True)
    reservas = db.relationship('Reserva', backref='instalacion', lazy=True)

    @property
    def roles_autorizados(self):
        return self.roles_permitidos.split(',') if self.roles_permitidos else ROLES_USUARIO

class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mensaje = db.Column(db.String(255), nullable=False)
    leida = db.Column(db.Boolean, nullable=False, default=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=hora_actual)

class Reserva(db.Model):
    __tablename__ = 'reservas'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    instalacion_id = db.Column(db.Integer, db.ForeignKey('instalaciones.id'), nullable=False)
    fecha_reserva = db.Column(db.Date, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    estado = db.Column(db.String(20), default='activa')
    tipo = db.Column(db.String(20), nullable=False, default='individual')
    id_recurrencia = db.Column(db.Integer, nullable=True)
    motivo = db.Column(db.String(200), nullable=True)

    @property
    def inicio(self):
        return datetime.combine(self.fecha_reserva, self.hora_inicio)

    def estado_actual(self, ahora):
        if self.estado == 'activa' and datetime.combine(self.fecha_reserva, self.hora_fin) <= ahora:
            return 'completada'
        return self.estado
