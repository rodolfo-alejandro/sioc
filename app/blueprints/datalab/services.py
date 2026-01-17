"""
Servicios de DataLab
"""
import pandas as pd
import os
from app.extensions import db
from app.models.dataset import Dataset
from app.services.file_storage import save_uploaded_file
from app.services.utils import normalize_column_name, detect_date_columns
from app.services.datalab_profiler import profile_dataset
from app.services.datalab_charts import generate_charts
from app.services.audit import audit_log


def process_uploaded_file(file, name, unidad_id, user_id):
    """
    Procesa un archivo subido y crea el dataset.
    
    Returns:
        tuple: (dataset, error_message)
    """
    try:
        # Guardar archivo
        file_path, safe_filename = save_uploaded_file(file, unidad_id)
        
        # Detectar tipo
        source_type = file.filename.rsplit('.', 1)[1].lower()
        
        # Leer con pandas
        try:
            if source_type == 'csv':
                # Intentar UTF-8 primero, luego latin-1
                try:
                    df = pd.read_csv(file_path, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, encoding='latin-1')
            else:
                # Excel
                df = pd.read_excel(file_path, sheet_name=0)  # Primera hoja
        except Exception as e:
            # Limpiar archivo si falla la lectura
            if os.path.exists(file_path):
                os.remove(file_path)
            return None, f"Error al leer el archivo: {str(e)}"
        
        # Normalizar nombres de columnas
        df.columns = [normalize_column_name(col) for col in df.columns]
        
        # Detectar y parsear fechas
        date_columns = detect_date_columns(df)
        for col in date_columns:
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce', infer_datetime_format=True)
            except:
                pass
        
        # Generar preview (primeras 100 filas)
        preview_df = df.head(100)
        preview_data = preview_df.to_dict('records')
        
        # Generar perfil
        profile = profile_dataset(df)
        
        # Generar gráficos
        charts = generate_charts(df, profile)
        
        # Crear dataset
        dataset = Dataset(
            unidad_id=unidad_id,
            user_id=user_id,
            name=name,
            source_type=source_type,
            original_filename=file.filename,
            stored_path=file_path,
            rows_count=len(df),
            columns_count=len(df.columns)
        )
        
        dataset.set_preview(preview_data)
        dataset.set_profile(profile)
        dataset.set_charts(charts)
        
        db.session.add(dataset)
        db.session.commit()
        
        # Auditoría
        audit_log('DATASET_UPLOADED', f'Dataset {name} subido ({len(df)} filas, {len(df.columns)} columnas)')
        
        return dataset, None
        
    except Exception as e:
        db.session.rollback()
        # Limpiar archivo si existe
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return None, f"Error al procesar el archivo: {str(e)}"


def get_user_datasets(user_id, unidad_id):
    """
    Obtiene los datasets de un usuario (filtrados por unidad).
    
    Returns:
        Query: Query de datasets
    """
    return Dataset.query.filter_by(unidad_id=unidad_id).order_by(Dataset.created_at.desc())


def get_dataset_by_id(dataset_id, unidad_id):
    """
    Obtiene un dataset por ID, verificando que pertenezca a la unidad.
    
    Returns:
        Dataset o None
    """
    return Dataset.query.filter_by(id=dataset_id, unidad_id=unidad_id).first()

