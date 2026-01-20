"""
Utilidades para manejo de fechas y horas en Argentina
"""
from datetime import datetime
import pytz

def get_argentina_now():
    """Obtiene la fecha y hora actual de Argentina"""
    argentina_tz = pytz.timezone('America/Argentina/Buenos_Aires')
    return datetime.now(argentina_tz).replace(tzinfo=None)  # Store as naive datetime in DB

def get_device_time():
    """Obtener hora del dispositivo (Argentina local time)"""
    # Usar la hora de Argentina para consistencia
    return get_argentina_now()

def get_argentina_date():
    """Obtiene la fecha actual de Argentina"""
    return get_argentina_now().date()

def format_argentina_datetime(dt=None):
    """Formatea una fecha/hora para mostrar en Argentina"""
    if dt is None:
        dt = get_argentina_now()
    
    if isinstance(dt, datetime):
        # Convertir a zona horaria de Argentina si no lo está
        if dt.tzinfo is None:
            argentina_tz = pytz.timezone('America/Argentina/Buenos_Aires')
            dt = argentina_tz.localize(dt)
        elif dt.tzinfo != pytz.timezone('America/Argentina/Buenos_Aires'):
            argentina_tz = pytz.timezone('America/Argentina/Buenos_Aires')
            dt = dt.astimezone(argentina_tz)
        
        return dt.strftime('%d/%m/%Y %H:%M:%S')
    
    return str(dt)

