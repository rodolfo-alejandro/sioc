"""
Formularios del módulo Sabana de Llamadas
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, TextAreaField, SelectField, IntegerField
from wtforms.validators import Optional, Length, DataRequired, NumberRange


def _coerce_int_optional(value):
    if value is None or value == '' or (isinstance(value, str) and value.strip() == ''):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class UploadGPRSForm(FlaskForm):
    """Subir archivo GPRS"""
    file = FileField('Archivo Excel GPRS', validators=[
        FileRequired(message='Seleccione un archivo'),
        FileAllowed(['xls', 'xlsx', 'xlsm'], 'Solo Excel (.xls, .xlsx, .xlsm)')
    ])
    operadora = SelectField('Operadora', choices=[], validators=[DataRequired(message='Seleccione operadora')])
    caso_id = SelectField(
        'Caso investigativo',
        coerce=int,
        choices=[],
        validators=[NumberRange(min=1, message='Seleccione un caso investigativo')],
    )
    sujeto_id = SelectField('Vincular a sujeto', coerce=_coerce_int_optional, validators=[Optional()], choices=[])


class UploadVOZForm(FlaskForm):
    """Subir archivo VOZ"""
    file = FileField('Archivo Excel VOZ', validators=[
        FileRequired(message='Seleccione un archivo'),
        FileAllowed(['xls', 'xlsx', 'xlsm'], 'Solo Excel (.xls, .xlsx, .xlsm)')
    ])
    operadora = SelectField('Operadora', choices=[], validators=[DataRequired(message='Seleccione operadora')])
    caso_id = SelectField(
        'Caso investigativo',
        coerce=int,
        choices=[],
        validators=[NumberRange(min=1, message='Seleccione un caso investigativo')],
    )
    sujeto_id = SelectField('Vincular a sujeto', coerce=_coerce_int_optional, validators=[Optional()], choices=[])


class SujetoForm(FlaskForm):
    """Crear/editar sujeto (persona de interés)"""
    apodo = StringField('Apodo', validators=[Optional(), Length(max=200)])
    nombre = StringField('Nombre', validators=[Optional(), Length(max=200)])
    dni = StringField('DNI', validators=[Optional(), Length(max=20)])
    observaciones = TextAreaField('Observaciones', validators=[Optional()])
    persona_id = SelectField('Vincular a persona (identificación)', coerce=_coerce_int_optional, validators=[Optional()], choices=[])
    imagen = FileField('Foto del sujeto', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Solo imágenes (jpg, png, gif, webp)')
    ])


class SujetoNuevoForm(SujetoForm):
    """Alta de sujeto: mismos campos + enlace opcional a caso (ap_caso_sujetos)."""
    caso_id = SelectField(
        'Caso investigativo (opcional)',
        coerce=_coerce_int_optional,
        validators=[Optional()],
        choices=[],
    )


class SujetoImagenForm(FlaskForm):
    """Solo imagen del sujeto"""
    imagen = FileField('Foto del sujeto', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Solo imágenes (jpg, png, gif, webp)')
    ])


class VincularCargaForm(FlaskForm):
    """Vincular una carga a caso (obligatorio) y sujeto (opcional)"""
    caso_id = SelectField(
        'Caso investigativo',
        coerce=int,
        choices=[],
        validators=[NumberRange(min=1, message='Seleccione un caso investigativo')],
    )
    sujeto_id = SelectField('Sujeto', coerce=_coerce_int_optional, validators=[Optional()], choices=[])
