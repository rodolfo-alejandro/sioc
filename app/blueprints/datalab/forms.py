"""
Formularios de DataLab
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, BooleanField
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


class UploadDenunciasForm(FlaskForm):
    """Formulario para subir archivo de denuncias web"""
    file = FileField('Archivo Excel de Denuncias', validators=[
        FileRequired(message='Debe seleccionar un archivo'),
        FileAllowed(['xlsx', 'xlsm'], message='Solo se permiten archivos Excel (.xlsx, .xlsm)')
    ])
    confirmar_eliminacion = BooleanField('Confirmo que deseo eliminar todos los datos actuales', 
                                        validators=[DataRequired(message='Debe confirmar la eliminación')])

