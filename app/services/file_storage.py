"""
Servicio de almacenamiento de archivos
"""
import os
from werkzeug.utils import secure_filename
from flask import current_app
from app.services.utils import get_safe_filename


def allowed_file(filename):
    """Verifica si la extensión del archivo está permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def save_uploaded_file(file, unidad_id):
    """
    Guarda un archivo subido en el sistema de archivos.
    
    Args:
        file: Archivo de Flask request.files
        unidad_id: ID de la unidad para organizar archivos
        
    Returns:
        tuple: (ruta_completa, nombre_seguro)
    """
    if not file or not allowed_file(file.filename):
        raise ValueError("Tipo de archivo no permitido")
    
    # Obtener configuración
    upload_folder = current_app.config['UPLOAD_FOLDER']
    max_size = current_app.config['MAX_CONTENT_LENGTH']
    
    # Verificar tamaño
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > max_size:
        raise ValueError(f"Archivo demasiado grande. Máximo: {max_size / (1024*1024):.1f}MB")
    
    # Crear directorio de unidad si no existe
    unidad_folder = os.path.join(upload_folder, str(unidad_id))
    os.makedirs(unidad_folder, exist_ok=True)
    
    # Generar nombre seguro
    original_filename = secure_filename(file.filename)
    import time
    timestamp = int(time.time())
    safe_name = get_safe_filename(original_filename, timestamp)
    
    # Ruta completa
    file_path = os.path.join(unidad_folder, safe_name)
    
    # Guardar archivo
    file.save(file_path)
    
    return file_path, safe_name

