"""
Servicio de perfilado de datasets para DataLab
"""
import pandas as pd
import numpy as np
from app.services.utils import detect_date_columns
from dateutil import parser as date_parser


def profile_dataset(df):
    """
    Genera un perfil estadístico básico del dataset.
    
    Args:
        df: DataFrame de pandas
    
    Returns:
        dict: Perfil con tipos, nulos, estadísticas numéricas y categóricas
    """
    profile = {
        'columns': {},
        'summary': {
            'total_rows': len(df),
            'total_columns': len(df.columns),
            'total_nulls': int(df.isnull().sum().sum())
        }
    }
    
    # Detectar columnas de fecha
    date_columns = detect_date_columns(df)
    
    for col in df.columns:
        col_data = df[col]
        col_type = str(col_data.dtype)
        
        col_profile = {
            'type': col_type,
            'nulls': int(col_data.isnull().sum()),
            'null_percentage': float((col_data.isnull().sum() / len(df)) * 100) if len(df) > 0 else 0.0,
            'unique_count': int(col_data.nunique())
        }
        
        # Intentar parsear fechas si el nombre sugiere que es fecha
        if col in date_columns:
            try:
                # Intentar convertir a datetime
                pd.to_datetime(col_data.dropna(), errors='coerce', infer_datetime_format=True)
                col_profile['type'] = 'datetime64[ns]'
                col_profile['is_date'] = True
            except:
                pass
        
        # Estadísticas para numéricas
        if pd.api.types.is_numeric_dtype(col_data):
            col_profile['min'] = float(col_data.min()) if not col_data.empty else None
            col_profile['max'] = float(col_data.max()) if not col_data.empty else None
            col_profile['mean'] = float(col_data.mean()) if not col_data.empty else None
            col_profile['median'] = float(col_data.median()) if not col_data.empty else None
            col_profile['std'] = float(col_data.std()) if not col_data.empty else None
        
        # Top valores para categóricas (o numéricas con pocos valores únicos)
        if col_data.nunique() <= 20 or not pd.api.types.is_numeric_dtype(col_data):
            value_counts = col_data.value_counts().head(10)
            col_profile['top_values'] = {
                str(k): int(v) for k, v in value_counts.items()
            }
        
        profile['columns'][col] = col_profile
    
    return profile

