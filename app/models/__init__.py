"""
Modelos de la aplicación SIOC
"""
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.unidad import Unidad
from app.models.audit_log import AuditLog
from app.models.dataset import Dataset
from app.models.denuncia_web import DenunciaWeb
from app.models.intervencion import Intervencion
from app.models.persona import Persona
from app.models.vehiculo import Vehiculo
from app.models.ubicacion import Ubicacion
from app.models.referencias import Sexo, Nacionalidad, EstadoCivil, Ocupacion, TipoContactoEmergencia
from app.models.territorial import Barrio, Comisaria, Jerarquia
from app.models.vehiculos import MarcaVehiculo, ModeloVehiculo, ColorVehiculo, TipoVehiculo
from app.models.control_comercial import (
    RubroComercial, Comercio, ComercioPropietario, ComercioEncargado,
    ControlComercial, InfraccionContravencional, ControlComercialInfraccion
)
from app.models.control_educativo import (
    TipoEstablecimiento, EstablecimientoEducativo, CargoEducativo,
    PersonalEducativo, ControlEducativo, PersonalEntrevistado
)
from app.models.entrevistas import (
    EntrevistaPuertaPuerta, PersonaEntrevista, CodigoQR, RespuestaQR
)
from app.models.grupos import GrupoIntervencion, PersonaGrupo
from app.models.relaciones import RelacionPersona, OrganizacionCriminal, PersonaOrganizacion
from app.models.operativos import TipoOperativo, OperativoActivo

__all__ = [
    'User', 'Role', 'Permission', 'Unidad', 'AuditLog', 'Dataset', 'DenunciaWeb',
    'Intervencion', 'Persona', 'Vehiculo', 'Ubicacion',
    'Sexo', 'Nacionalidad', 'EstadoCivil', 'Ocupacion', 'TipoContactoEmergencia',
    'Barrio', 'Comisaria', 'Jerarquia',
    'MarcaVehiculo', 'ModeloVehiculo', 'ColorVehiculo', 'TipoVehiculo',
    'RubroComercial', 'Comercio', 'ComercioPropietario', 'ComercioEncargado',
    'ControlComercial', 'InfraccionContravencional', 'ControlComercialInfraccion',
    'TipoEstablecimiento', 'EstablecimientoEducativo', 'CargoEducativo',
    'PersonalEducativo', 'ControlEducativo', 'PersonalEntrevistado',
    'EntrevistaPuertaPuerta', 'PersonaEntrevista', 'CodigoQR', 'RespuestaQR',
    'GrupoIntervencion', 'PersonaGrupo',
    'RelacionPersona', 'OrganizacionCriminal', 'PersonaOrganizacion',
    'TipoOperativo', 'OperativoActivo'
]

