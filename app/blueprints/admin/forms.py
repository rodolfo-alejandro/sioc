"""
Formularios de Administración
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, BooleanField, PasswordField, SelectMultipleField
from wtforms.validators import DataRequired, Email, Length, Optional
from app.models.unidad import Unidad
from app.models.role import Role
from app.models.permission import Permission


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
    permissions = SelectMultipleField('Permisos adicionales', coerce=int, validators=[Optional()])
    active = BooleanField('Activo', default=True)
    must_change_password = BooleanField('Debe cambiar contraseña', default=False)
    
    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        # Cargar opciones de unidades (incluye inactivas para evitar errores al editar usuarios existentes)
        self.unidad_id.choices = [
            (u.id, f"{u.nombre}{'' if u.activo else ' (inactiva)'}")
            for u in Unidad.query.order_by(Unidad.nombre).all()
        ]
        # Cargar opciones de roles
        self.role_id.choices = [(r.id, r.name) for r in Role.query.order_by(Role.name).all()]
        # Cargar opciones de permisos adicionales
        self.permissions.choices = [(p.id, p.code) for p in Permission.query.order_by(Permission.code).all()]


class UnidadForm(FlaskForm):
    """Formulario para crear/editar dependencias (unidades)."""
    nombre = StringField('Nombre', validators=[DataRequired(), Length(min=2, max=200)])
    activo = BooleanField('Activa', default=True)

