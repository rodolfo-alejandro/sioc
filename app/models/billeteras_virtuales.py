"""
Modelos para análisis de movimientos de billeteras virtuales.
"""
from datetime import datetime

from app.extensions import db


class BilleteraCarga(db.Model):
    __tablename__ = "bv_cargas"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # movimientos | salidas
    tipo_archivo = db.Column(db.String(20), nullable=False, index=True)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    archivo_hash = db.Column(db.String(64), nullable=False, index=True)

    registros_total = db.Column(db.Integer, nullable=False, default=0)
    registros_validos = db.Column(db.Integer, nullable=False, default=0)
    fecha_min = db.Column(db.DateTime, nullable=True)
    fecha_max = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    movimientos = db.relationship(
        "BilleteraMovimiento",
        backref="carga",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    salidas = db.relationship(
        "BilleteraSalida",
        backref="carga",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class BilleteraMovimiento(db.Model):
    __tablename__ = "bv_movimientos"

    id = db.Column(db.Integer, primary_key=True)
    carga_id = db.Column(db.Integer, db.ForeignKey("bv_cargas.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)

    tipo_dato_consulta = db.Column(db.String(120), nullable=True)
    tipo_dato = db.Column(db.String(80), nullable=True)
    dato = db.Column(db.String(150), nullable=True, index=True)
    apodo = db.Column(db.String(150), nullable=True)

    tipo_movimiento = db.Column(db.String(80), nullable=True, index=True)
    fecha_operacion = db.Column(db.DateTime, nullable=True, index=True)
    payment_id = db.Column(db.String(80), nullable=True, index=True)
    order_id = db.Column(db.String(80), nullable=True)
    estado_payment = db.Column(db.String(60), nullable=True, index=True)
    total_pagado = db.Column(db.Numeric(18, 2), nullable=True, index=True)

    id_buyer = db.Column(db.String(80), nullable=True, index=True)
    apodo_buyer = db.Column(db.String(200), nullable=True)
    nombre_buyer = db.Column(db.String(200), nullable=True, index=True)
    documento_buyer = db.Column(db.String(80), nullable=True, index=True)

    id_seller = db.Column(db.String(80), nullable=True, index=True)
    apodo_seller = db.Column(db.String(200), nullable=True)
    nombre_seller = db.Column(db.String(200), nullable=True, index=True)

    metodo_pago = db.Column(db.String(200), nullable=True, index=True)
    origen_transferencia = db.Column(db.String(200), nullable=True)
    documento_origen_account = db.Column(db.String(80), nullable=True)
    nombre_origen_account = db.Column(db.String(200), nullable=True)
    destino_transferencia = db.Column(db.String(200), nullable=True)
    destino_tipo_transferencia = db.Column(db.String(120), nullable=True)
    documento_destino_account = db.Column(db.String(80), nullable=True, index=True)
    nombre_destino_account = db.Column(db.String(200), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class BilleteraSalida(db.Model):
    __tablename__ = "bv_salidas"

    id = db.Column(db.Integer, primary_key=True)
    carga_id = db.Column(db.Integer, db.ForeignKey("bv_cargas.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)

    tipo_dato_consulta = db.Column(db.String(120), nullable=True)
    tipo_dato = db.Column(db.String(80), nullable=True)
    dato = db.Column(db.String(150), nullable=True, index=True)
    apodo = db.Column(db.String(150), nullable=True)

    fecha_operacion = db.Column(db.DateTime, nullable=True, index=True)
    id_usuario_origen = db.Column(db.String(80), nullable=True, index=True)
    id_retiro = db.Column(db.String(80), nullable=True, index=True)
    detalle = db.Column(db.String(200), nullable=True)
    monto_retirado = db.Column(db.Numeric(18, 2), nullable=True, index=True)
    estado = db.Column(db.String(50), nullable=True, index=True)

    titular_origen = db.Column(db.String(200), nullable=True)
    titular_destino = db.Column(db.String(200), nullable=True, index=True)
    documento_destino = db.Column(db.String(80), nullable=True, index=True)
    cuenta_destino = db.Column(db.String(120), nullable=True)
    entidad = db.Column(db.String(200), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
