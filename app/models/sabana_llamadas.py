"""
Modelos del módulo Sabana de Llamadas (GPRS y VOZ).
Sujeto = persona de interés (apodo, nombre, DNI, imagen).
Carga = cada importación de archivo (GPRS o VOZ) vinculada a un sujeto.
"""
from datetime import datetime
from app.extensions import db


class Sujeto(db.Model):
    """Persona de interés para análisis de llamadas. Puede vincularse a Persona (identificación) después."""
    __tablename__ = 'sabana_sujetos'

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    apodo = db.Column(db.String(200), nullable=True, index=True)
    nombre = db.Column(db.String(200), nullable=True, index=True)
    dni = db.Column(db.String(20), nullable=True, index=True)
    observaciones = db.Column(db.Text, nullable=True)
    imagen = db.Column(db.String(500), nullable=True)

    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    unidad = db.relationship('Unidad', backref='sabana_sujetos')
    user = db.relationship('User', backref='sabana_sujetos')
    persona = db.relationship('Persona', backref='sabana_sujetos', foreign_keys=[persona_id])

    def display_name(self):
        if self.nombre:
            return self.nombre
        if self.apodo:
            return self.apodo
        if self.dni:
            return f"DNI {self.dni}"
        return f"Sujeto #{self.id}"

    def __repr__(self):
        return f'<Sujeto {self.id}: {self.display_name()}>'


class CargaLlamada(db.Model):
    """Cada importación de un archivo GPRS o VOZ, vinculada a un sujeto."""
    __tablename__ = 'sabana_cargas'

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sujeto_id = db.Column(db.Integer, db.ForeignKey('sabana_sujetos.id'), nullable=True, index=True)
    caso_id = db.Column(db.Integer, db.ForeignKey('ap_casos.id'), nullable=True, index=True)

    tipo = db.Column(db.String(10), nullable=False, index=True)
    operadora = db.Column(db.String(30), nullable=True, index=True)  # PERSONAL / MOVISTAR / CLARO / OTRA
    nombre_archivo = db.Column(db.String(255), nullable=True)
    rango_desde = db.Column(db.DateTime, nullable=True)
    rango_hasta = db.Column(db.DateTime, nullable=True)
    criterio_busqueda = db.Column(db.Text, nullable=True)
    processing_detail = db.Column(db.Text, nullable=True)  # JSON con trazabilidad de importación
    sha256 = db.Column(db.String(128), nullable=True, index=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    # Nota opcional en pantalla Relaciones del caso (no confundir con “fuente” policial)
    relaciones_nota = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unidad = db.relationship('Unidad', backref='sabana_cargas')
    user = db.relationship('User', backref='sabana_cargas')
    sujeto = db.relationship('Sujeto', backref='cargas', foreign_keys=[sujeto_id])
    caso = db.relationship('AnalisisPuntoCaso', foreign_keys=[caso_id], backref='sabana_cargas')

    def __repr__(self):
        return f'<CargaLlamada {self.id} {self.tipo}>'


class CargaLlamadaCompartida(db.Model):
    """
    Permite compartir una carga (archivo) con otro usuario de la misma unidad.
    PK compuesto: (carga_id, shared_with_user_id)
    """
    __tablename__ = 'sabana_cargas_compartidas'

    carga_id = db.Column(db.Integer, db.ForeignKey('sabana_cargas.id'), primary_key=True, nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True, nullable=False, index=True)
    shared_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    carga = db.relationship('CargaLlamada', backref='compartidos', foreign_keys=[carga_id])
    shared_with = db.relationship('User', foreign_keys=[shared_with_user_id])
    shared_by = db.relationship('User', foreign_keys=[shared_by_user_id])


class SujetoCompartido(db.Model):
    """
    Permite compartir un sujeto completo (y por extensión sus cargas) con otro usuario.
    PK compuesto: (sujeto_id, shared_with_user_id)
    """
    __tablename__ = 'sabana_sujetos_compartidos'

    sujeto_id = db.Column(db.Integer, db.ForeignKey('sabana_sujetos.id'), primary_key=True, nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True, nullable=False, index=True)
    shared_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sujeto = db.relationship('Sujeto', backref='compartidos', foreign_keys=[sujeto_id])
    shared_with = db.relationship('User', foreign_keys=[shared_with_user_id])
    shared_by = db.relationship('User', foreign_keys=[shared_by_user_id])


class SujetoNumero(db.Model):
    """
    Relación explícita entre Sujeto y Número telefónico.
    Permite fijar a qué sujeto pertenece un número, independientemente de en qué cargas aparezca.
    """
    __tablename__ = 'sabana_sujeto_numeros'

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    sujeto_id = db.Column(db.Integer, db.ForeignKey('sabana_sujetos.id'), nullable=False, index=True)
    numero = db.Column(db.String(64), nullable=False, index=True)
    notas = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unidad = db.relationship('Unidad', backref='sabana_sujeto_numeros')
    sujeto = db.relationship('Sujeto', backref='numeros_explicit', foreign_keys=[sujeto_id])

    def __repr__(self):
        return f'<SujetoNumero sujeto={self.sujeto_id} numero={self.numero}>'


class ResultadoTraficoGPRS(db.Model):
    """Registros de la hoja 'Resultado de Trafico' de un archivo GPRS."""
    __tablename__ = 'sabana_trafico_gprs'

    id = db.Column(db.Integer, primary_key=True)
    carga_id = db.Column(db.Integer, db.ForeignKey('sabana_cargas.id'), nullable=False, index=True)

    imei = db.Column(db.String(50), nullable=True, index=True)
    imsi = db.Column(db.String(50), nullable=True, index=True)
    numero = db.Column(db.String(64), nullable=True, index=True)
    fecha = db.Column(db.DateTime, nullable=True, index=True)
    hora = db.Column(db.String(20), nullable=True)
    duracion = db.Column(db.String(50), nullable=True)
    ip = db.Column(db.String(100), nullable=True)
    ip_dual_stack = db.Column(db.String(100), nullable=True)
    volumen_kb = db.Column(db.String(50), nullable=True)
    celda = db.Column(db.String(100), nullable=True, index=True)
    celda_direccion = db.Column(db.String(255), nullable=True)
    celda_localidad = db.Column(db.String(200), nullable=True)
    celda_provincia = db.Column(db.String(200), nullable=True)
    ip_wifi = db.Column(db.String(100), nullable=True)
    extras = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    carga = db.relationship('CargaLlamada', backref='registros_gprs', foreign_keys=[carga_id])

    def __repr__(self):
        return f'<ResultadoTraficoGPRS {self.id}>'


class ResultadoTraficoVOZ(db.Model):
    """Registros de la hoja 'Resultado de Trafico' de un archivo VOZ."""
    __tablename__ = 'sabana_trafico_voz'

    id = db.Column(db.Integer, primary_key=True)
    carga_id = db.Column(db.Integer, db.ForeignKey('sabana_cargas.id'), nullable=False, index=True)

    imei = db.Column(db.String(50), nullable=True, index=True)
    imsi = db.Column(db.String(50), nullable=True, index=True)
    numero = db.Column(db.String(64), nullable=True, index=True)
    fecha = db.Column(db.DateTime, nullable=True, index=True)
    hora = db.Column(db.String(20), nullable=True)
    tipo = db.Column(db.String(50), nullable=True)
    duracion = db.Column(db.String(50), nullable=True)
    otro = db.Column(db.String(255), nullable=True)
    celda_id = db.Column(db.String(100), nullable=True, index=True)
    celda_calle_altura = db.Column(db.String(255), nullable=True)
    celda_localidad = db.Column(db.String(200), nullable=True)
    celda_provincia = db.Column(db.String(200), nullable=True)
    extras = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    carga = db.relationship('CargaLlamada', backref='registros_voz', foreign_keys=[carga_id])

    def __repr__(self):
        return f'<ResultadoTraficoVOZ {self.id}>'


class DatoTecnico(db.Model):
    """Hoja 'Datos Tecnicos' (común estructura GPRS y VOZ). Tiene Lat/Long para mapa."""
    __tablename__ = 'sabana_datos_tecnicos'

    id = db.Column(db.Integer, primary_key=True)
    carga_id = db.Column(db.Integer, db.ForeignKey('sabana_cargas.id'), nullable=False, index=True)
    tipo = db.Column(db.String(10), nullable=False, index=True)

    celda_id = db.Column(db.String(100), nullable=True, index=True)  # CeldaID para enlazar con resultado de tráfico
    rango_consulta = db.Column(db.String(100), nullable=True, index=True)
    celda_direccion = db.Column(db.String(255), nullable=True)
    celda_loc = db.Column(db.String(200), nullable=True)
    celda_prov = db.Column(db.String(200), nullable=True)
    rad_cob_km = db.Column(db.String(50), nullable=True)
    azimuth = db.Column(db.String(50), nullable=True)
    lat = db.Column(db.Float, nullable=True, index=True)
    long = db.Column(db.Float, nullable=True, index=True)
    a_horiz = db.Column(db.String(50), nullable=True)
    a_vert = db.Column(db.String(50), nullable=True)
    extras = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    carga = db.relationship('CargaLlamada', backref='datos_tecnicos', foreign_keys=[carga_id])

    def __repr__(self):
        return f'<DatoTecnico {self.id} {self.tipo}>'


class SabanaImpactoNota(db.Model):
    """
    Nota del investigador sobre un impacto concreto (registro de tráfico).
    Se identifica por (unidad, tipo, impacto_id, user).
    """
    __tablename__ = 'sabana_impacto_notas'

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    tipo = db.Column(db.String(10), nullable=False, index=True)  # 'gprs' / 'voz'
    impacto_id = db.Column(db.Integer, nullable=False, index=True)
    color = db.Column(db.String(20), nullable=True)  # ej. 'rojo', 'amarillo', 'verde', 'azul'
    nota = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    unidad = db.relationship('Unidad', backref='sabana_impacto_notas')
    user = db.relationship('User', backref='sabana_impacto_notas')

    def __repr__(self):
        return f'<SabanaImpactoNota {self.id} {self.tipo}#{self.impacto_id}>'
