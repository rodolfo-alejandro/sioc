"""
Formularios de Administración
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, PasswordField
from wtforms.validators import DataRequired, Email, Length, Optional
from app.models.unidad import Unidad
from app.models.role import Role


class UserForm(FlaskForm):
    """Formulario para crear/editar usuario"""
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[
        Optional(),
        Length(min=8, message='La contraseña debe tener al menos 8 caracteres')
    ])
    unidad_id = SelectField('Unidad', coerce=int, validators=[DataRequired()])
    role_id = SelectField('Rol', coerce=int, validators=[DataRequired()])
    active = BooleanField('Activo', default=True)
    must_change_password = BooleanField('Debe cambiar contraseña', default=False)
    
    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        # Cargar opciones de unidades
        self.unidad_id.choices = [(u.id, u.nombre) for u in Unidad.query.filter_by(activo=True).order_by(Unidad.nombre).all()]
        # Cargar opciones de roles
        self.role_id.choices = [(r.id, r.name) for r in Role.query.order_by(Role.name).all()]

