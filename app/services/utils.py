"""
Utilidades generales
"""
import re
from datetime import datetime


def normalize_column_name(name):
    """
    Normaliza el nombre de una columna:
    - Strip espacios
    - Reemplaza espacios por _
    - Convierte a minúsculas
    - Elimina caracteres raros
    """
    if not name or not isinstance(name, str):
        return 'columna_sin_nombre'
    
    # Strip
    name = name.strip()
    
    # Reemplazar espacios y caracteres especiales por _
    name = re.sub(r'[^\w\s]', '_', name)
    name = re.sub(r'\s+', '_', name)
    
    # Minúsculas
    name = name.lower()
    
    # Eliminar múltiples guiones bajos
    name = re.sub(r'_+', '_', name)
    
    # Eliminar guiones bajos al inicio/final
    name = name.strip('_')
    
    # Si quedó vacío, dar nombre por defecto
    if not name:
        name = 'columna_sin_nombre'
    
    return name


def detect_date_columns(df):
    """
    Detecta columnas que parecen fechas basándose en el nombre.
    
    Returns:
        list: Lista de nombres de columnas que parecen fechas
    """
    date_keywords = ['fecha', 'date', 'datetime', 'hora', 'time', 'timestamp', 
                     'inicio', 'fin', 'desde', 'hasta', 'created', 'updated']
    
    date_columns = []
    for col in df.columns:
        col_lower = str(col).lower()
        if any(keyword in col_lower for keyword in date_keywords):
            date_columns.append(col)
    
    return date_columns


def get_safe_filename(original_filename, timestamp=None):
    """
    Genera un nombre de archivo seguro con timestamp.
    
    Args:
        original_filename: Nombre original del archivo
        timestamp: Timestamp opcional (si None, usa el actual)
    
    Returns:
        str: Nombre de archivo seguro
    """
    from werkzeug.utils import secure_filename
    
    if timestamp is None:
        timestamp = int(datetime.now().timestamp())
    
    # Obtener nombre seguro
    safe_name = secure_filename(original_filename)
    
    # Separar nombre y extensión
    if '.' in safe_name:
        name, ext = safe_name.rsplit('.', 1)
        return f"{timestamp}_{name}.{ext}"
    else:
        return f"{timestamp}_{safe_name}"

