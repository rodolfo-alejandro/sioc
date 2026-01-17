"""
Servicio de generación de gráficos para DataLab
"""
import pandas as pd
import numpy as np
from app.services.utils import detect_date_columns


def generate_charts(df, profile):
    """
    Genera especificaciones de gráficos automáticos basados en el dataset.
    
    Args:
        df: DataFrame de pandas
        profile: Perfil del dataset generado por profile_dataset
    
    Returns:
        dict: Diccionario con especificaciones de gráficos para Plotly
    """
    charts = {}
    chart_id = 1
    
    # Detectar columnas de fecha
    date_columns = detect_date_columns(df)
    
    # 1. Gráficos de barras para categóricas (top 10)
    for col in df.columns:
        col_profile = profile['columns'].get(col, {})
        
        # Si es categórica o tiene pocos valores únicos
        if col_profile.get('unique_count', 0) <= 20 and col_profile.get('unique_count', 0) > 0:
            top_values = col_profile.get('top_values', {})
            if top_values:
                charts[f'chart_{chart_id}'] = {
                    'type': 'bar',
                    'title': f'Top valores: {col}',
                    'data': {
                        'x': list(top_values.keys()),
                        'y': list(top_values.values())
                    },
                    'xaxis': col,
                    'yaxis': 'Cantidad'
                }
                chart_id += 1
    
    # 2. Histogramas para numéricas
    for col in df.columns:
        col_data = df[col]
        if pd.api.types.is_numeric_dtype(col_data) and col not in date_columns:
            # Crear bins para histograma
            try:
                hist, bins = np.histogram(col_data.dropna(), bins=20)
                charts[f'chart_{chart_id}'] = {
                    'type': 'histogram',
                    'title': f'Distribución: {col}',
                    'data': {
                        'x': col_data.dropna().tolist(),
                        'bins': 20
                    },
                    'xaxis': col,
                    'yaxis': 'Frecuencia'
                }
                chart_id += 1
            except:
                pass
    
    # 3. Gráficos de línea temporal (fecha + numérica)
    for date_col in date_columns:
        try:
            df_date = df.copy()
            df_date[date_col] = pd.to_datetime(df_date[date_col], errors='coerce')
            
            # Buscar columnas numéricas para graficar
            numeric_cols = [c for c in df.columns 
                          if pd.api.types.is_numeric_dtype(df[c]) and c != date_col]
            
            if numeric_cols:
                # Tomar la primera numérica
                num_col = numeric_cols[0]
                
                # Agrupar por fecha y sumar/promediar
                df_grouped = df_date.groupby(df_date[date_col].dt.date)[num_col].mean().reset_index()
                df_grouped = df_grouped.sort_values(date_col)
                
                charts[f'chart_{chart_id}'] = {
                    'type': 'line',
                    'title': f'Tendencia temporal: {num_col}',
                    'data': {
                        'x': [str(d) for d in df_grouped[date_col].tolist()],
                        'y': df_grouped[num_col].tolist()
                    },
                    'xaxis': date_col,
                    'yaxis': num_col
                }
                chart_id += 1
        except Exception as e:
            print(f"Error generando gráfico temporal: {e}")
            pass
    
    return charts

