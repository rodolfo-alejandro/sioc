"""
Formularios WTForms para el módulo de Intervenciones
"""
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DateField, SelectField, TextAreaField, FloatField
from wtforms.validators import DataRequired, Optional, Length, NumberRange

class IdentificacionPersonaForm(FlaskForm):
    """Formulario para identificación de persona"""
    dni = StringField('DNI', validators=[DataRequired(), Length(min=7, max=10)])
    nombre = StringField('Nombre', validators=[DataRequired(), Length(max=100)])
    apellido = StringField('Apellido', validators=[DataRequired(), Length(max=100)])
    fecha_nacimiento = DateField('Fecha de Nacimiento', validators=[Optional()])
    sexo_id = SelectField('Sexo', coerce=int, validators=[Optional()])
    nacionalidad_id = SelectField('Nacionalidad', coerce=int, validators=[Optional()])
    estado_civil_id = SelectField('Estado Civil', coerce=int, validators=[Optional()])
    ocupacion_id = SelectField('Ocupación', coerce=int, validators=[Optional()])
    direccion = StringField('Domicilio', validators=[Optional(), Length(max=200)])
    telefono = StringField('Teléfono', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Length(max=120)])
    contacto_emergencia_nombre = StringField('Contacto Emergencia - Nombre', validators=[Optional(), Length(max=100)])
    contacto_emergencia_telefono = StringField('Contacto Emergencia - Teléfono', validators=[Optional(), Length(max=20)])
    contacto_emergencia_relacion_id = SelectField('Contacto Emergencia - Relación', coerce=int, validators=[Optional()])
    latitud = FloatField('Latitud', validators=[DataRequired()])
    longitud = FloatField('Longitud', validators=[DataRequired()])
    observaciones = TextAreaField('Observaciones', validators=[Optional(), Length(max=1000)])

class ControlVehicularForm(FlaskForm):
    """Formulario para control vehicular"""
    patente = StringField('Patente', validators=[DataRequired(), Length(max=10)])
    marca_id = SelectField('Marca', coerce=int, validators=[Optional()])
    modelo_id = SelectField('Modelo', coerce=int, validators=[Optional()])
    color_id = SelectField('Color', coerce=int, validators=[Optional()])
    tipo_vehiculo_id = SelectField('Tipo de Vehículo', coerce=int, validators=[Optional()])
    dni_conductor = StringField('DNI Conductor', validators=[Optional(), Length(max=10)])
    latitud = FloatField('Latitud', validators=[DataRequired()])
    longitud = FloatField('Longitud', validators=[DataRequired()])
    observaciones = TextAreaField('Observaciones', validators=[Optional(), Length(max=1000)])

