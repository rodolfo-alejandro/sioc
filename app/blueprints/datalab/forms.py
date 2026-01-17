"""
Formularios de DataLab
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField
from wtforms.validators import DataRequired, Length
from flask import current_app


class UploadDatasetForm(FlaskForm):
    """Formulario para subir dataset"""
    name = StringField('Nombre del dataset', validators=[
        DataRequired(), 
        Length(min=3, max=200, message='El nombre debe tener entre 3 y 200 caracteres')
    ])
    file = FileField('Archivo', validators=[
        FileRequired(message='Debe seleccionar un archivo'),
        FileAllowed(['xlsx', 'xlsm', 'csv'], message='Solo se permiten archivos Excel (.xlsx, .xlsm) o CSV')
    ])

