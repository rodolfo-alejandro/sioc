"""
Servicios para el módulo de Denuncias Web
"""
import pandas as pd
import os
from datetime import datetime
from app.extensions import db
from app.models.denuncia_web import DenunciaWeb
from app.services.file_storage import save_uploaded_file
from app.services.utils import normalize_column_name
from app.services.audit import audit_log


def mapear_columna_excel(col_name):
    """Mapea nombres de columnas del Excel a campos del modelo"""
    mapeo = {
        'ID': 'id_excel',
        'Nº AP': 'numero_ap',
        'FECHA DE CARGA': 'fecha_carga',
        'FECHA DE REGISTRO': 'fecha_registro',
        'FECHA DEL HECHO': 'fecha_hecho',
        'HORA': 'hora_hecho',
        'DIA': 'dia',
        'MES': 'mes',
        'DEPARTAMENTO': 'departamento',
        'DIVISION': 'division',
        'SINAR A CARGO AP': 'sinar_a_cargo_ap',
        'SINAR A CARGO': 'sinar_a_cargo',
        'CARATULA': 'caratula',
        'TIPO/ORIGEN': 'tipo_origen',
        'LUGAR DEL HECHO': 'lugar_hecho',
        'LATITUD - LONGITUD': 'latitud_longitud',
        'BARRIO': 'barrio_id',
        'NOMBRE DE BARRIO': 'nombre_barrio',
        'JURISDICCION (DSTO/SCRIA/CRIA)': 'jurisdiccion',
        'SECTOR': 'sector',
        'DISTRITO DE PREVENCION': 'distrito_prevencion',
        'LOCALIDAD': 'localidad',
        'MUNICIPIO': 'municipio',
        'T.DEPARTAMENTAL': 't_departamental',
        'RELATO DEL HECHO': 'relato_hecho',
        'FISCALIA': 'fiscalia',
        'JUZGADO': 'juzgado',
        'CAUSA Nº': 'causa_numero',
        'ACUSADO': 'acusado',
        'EDAD': 'edad',
        'DNI': 'dni',
        'DLIO': 'dlio',
        'ALIAS': 'alias',
        'ESTADOS': 'estados',
        'ESTADO': 'estado',
        'ESTADO_NOMBRE': 'estado_nombre',
        'VINCULADA A': 'vinculada_a',
        'VINCULADA CON AP': 'vinculada_con_ap',
        'ACCIONES DESPLEGADAS': 'acciones_desplegadas',
        'ARCHIVO ADJUNTO': 'archivo_adjunto',
        'AVANCE': 'avance',
        'FECHA ELEVACION': 'fecha_elevacion',
        'OBSERVACIONES': 'observaciones',
        'ACTUARIO': 'actuario_id',
        'NOMBRE DEL ACTUARIO': 'nombre_actuario',
        'FECHA DE ULTIMA ACTUALIZACION': 'fecha_ultima_actualizacion'
    }
    return mapeo.get(col_name, None)


def parsear_fecha(valor):
    """Intenta parsear una fecha desde diferentes formatos"""
    if pd.isna(valor) or valor is None:
        return None
    
    if isinstance(valor, datetime):
        return valor
    
    if isinstance(valor, str):
        try:
            return pd.to_datetime(valor, errors='coerce')
        except:
            return None
    
    try:
        return pd.to_datetime(valor, errors='coerce')
    except:
        return None


def procesar_archivo_denuncias(file, unidad_id, user_id, eliminar_existentes=True):
    """
    Procesa un archivo Excel de denuncias y lo carga en la base de datos.
    
    Args:
        file: Archivo Excel subido
        unidad_id: ID de la unidad
        user_id: ID del usuario que carga
        eliminar_existentes: Si True, elimina todas las denuncias existentes antes de cargar
    
    Returns:
        tuple: (cantidad_cargada, error_message)
    """
    try:
        # Guardar archivo temporalmente
        file_path, safe_filename = save_uploaded_file(file, unidad_id)
        
        # Leer Excel
        try:
            df = pd.read_excel(file_path, sheet_name=0)
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            return None, f"Error al leer el archivo: {str(e)}"
        
        # Validar columnas mínimas requeridas
        columnas_requeridas = ['ID', 'FECHA DE REGISTRO']
        columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]
        if columnas_faltantes:
            if os.path.exists(file_path):
                os.remove(file_path)
            return None, f"Columnas faltantes: {', '.join(columnas_faltantes)}"
        
        # Eliminar denuncias existentes si se solicita
        if eliminar_existentes:
            cantidad_eliminada = DenunciaWeb.query.filter_by(unidad_id=unidad_id).delete()
            db.session.commit()
            audit_log('DENUNCIAS_DELETED', f'Eliminadas {cantidad_eliminada} denuncias antes de cargar nuevas')
        
        # Procesar cada fila
        denuncias_creadas = 0
        errores = []
        
        for idx, row in df.iterrows():
            try:
                denuncia = DenunciaWeb()
                denuncia.unidad_id = unidad_id
                denuncia.user_id = user_id
                
                # Mapear columnas
                for col_excel, valor in row.items():
                    campo_modelo = mapear_columna_excel(col_excel)
                    if campo_modelo and hasattr(denuncia, campo_modelo):
                        # Manejar fechas
                        if 'fecha' in campo_modelo.lower():
                            fecha_parsed = parsear_fecha(valor)
                            if not pd.isna(fecha_parsed) and fecha_parsed is not None:
                                setattr(denuncia, campo_modelo, fecha_parsed.to_pydatetime() if hasattr(fecha_parsed, 'to_pydatetime') else fecha_parsed)
                        # Manejar valores numéricos
                        elif campo_modelo in ['numero_ap', 'barrio_id', 'actuario_id', 'edad', 'estado', 'avance']:
                            if not pd.isna(valor):
                                try:
                                    setattr(denuncia, campo_modelo, float(valor))
                                except:
                                    pass
                        # Manejar texto
                        else:
                            if not pd.isna(valor):
                                valor_str = str(valor).strip()
                                if valor_str:
                                    # Limitar longitud según el campo
                                    # Campos que pueden ser largos
                                    campos_largos = ['relato_hecho', 'acciones_desplegadas', 'observaciones', 'lugar_hecho', 'caratula']
                                    # Campos de tamaño medio
                                    campos_medios = ['dlio', 'nombre_barrio', 'departamento', 'division', 'sinar_a_cargo', 'jurisdiccion']
                                    
                                    if campo_modelo in campos_largos:
                                        max_length = 500
                                    elif campo_modelo in campos_medios:
                                        max_length = 500
                                    else:
                                        max_length = 200
                                    
                                    if len(valor_str) > max_length:
                                        valor_str = valor_str[:max_length]
                                    setattr(denuncia, campo_modelo, valor_str)
                
                # Guardar acusados adicionales como JSON
                acusados_adicionales = []
                if not pd.isna(row.get('ACUSADO2', None)):
                    acusados_adicionales.append({
                        'nombre': str(row.get('ACUSADO2', '')),
                        'edad': float(row.get('EDAD2', 0)) if not pd.isna(row.get('EDAD2', None)) else None,
                        'dni': str(row.get('DNI2', '')) if not pd.isna(row.get('DNI2', None)) else None,
                        'dlio': str(row.get('DLIO2', '')) if not pd.isna(row.get('DLIO2', None)) else None,
                        'alias': str(row.get('ALIAS2', '')) if not pd.isna(row.get('ALIAS2', None)) else None
                    })
                if not pd.isna(row.get('ACUSADO3', None)):
                    acusados_adicionales.append({
                        'nombre': str(row.get('ACUSADO3', '')),
                        'edad': float(row.get('EDAD3', 0)) if not pd.isna(row.get('EDAD3', None)) else None,
                        'dni': str(row.get('DNI3', '')) if not pd.isna(row.get('DNI3', None)) else None,
                        'dlio': str(row.get('DLIO3', '')) if not pd.isna(row.get('DLIO3', None)) else None,
                        'alias': str(row.get('ALIAS3', '')) if not pd.isna(row.get('ALIAS3', None)) else None
                    })
                
                if acusados_adicionales:
                    import json
                    denuncia.acusados_json = json.dumps(acusados_adicionales, ensure_ascii=False)
                
                # Calcular días de investigación
                denuncia.dias_investigacion = denuncia.calcular_dias_investigacion()
                
                db.session.add(denuncia)
                denuncias_creadas += 1
                
                # Commit en lotes de 100
                if denuncias_creadas % 100 == 0:
                    db.session.commit()
                    
            except Exception as e:
                errores.append(f"Fila {idx + 2}: {str(e)}")
                continue
        
        # Commit final
        db.session.commit()
        
        # Limpiar archivo temporal
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        
        # Auditoría
        audit_log('DENUNCIAS_UPLOADED', f'Cargadas {denuncias_creadas} denuncias. Errores: {len(errores)}')
        
        mensaje_error = None
        if errores and len(errores) > 10:
            mensaje_error = f"Algunas filas tuvieron errores. Cargadas: {denuncias_creadas}, Errores: {len(errores)}"
        elif errores:
            mensaje_error = f"Errores en algunas filas: {'; '.join(errores[:5])}"
        
        return denuncias_creadas, mensaje_error
        
    except Exception as e:
        db.session.rollback()
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return None, f"Error al procesar el archivo: {str(e)}"


def aplicar_filtros(query, filtros):
    """Aplica filtros a una query de DenunciaWeb"""
    if not filtros:
        return query
    
    # Filtros de selección múltiple
    if filtros.get('tipos'):
        query = query.filter(DenunciaWeb.tipo_origen.in_(filtros['tipos']))
    if filtros.get('departamentos'):
        query = query.filter(DenunciaWeb.departamento.in_(filtros['departamentos']))
    if filtros.get('divisiones'):
        query = query.filter(DenunciaWeb.division.in_(filtros['divisiones']))
    if filtros.get('secciones'):
        query = query.filter(DenunciaWeb.sinar_a_cargo.in_(filtros['secciones']))
    if filtros.get('estados'):
        query = query.filter(DenunciaWeb.estado_nombre.in_(filtros['estados']))
    if filtros.get('actuarios'):
        query = query.filter(DenunciaWeb.nombre_actuario.in_(filtros['actuarios']))
    
    # Filtros de rango por fecha de registro
    if filtros.get('fecha_desde'):
        query = query.filter(DenunciaWeb.fecha_registro >= filtros['fecha_desde'])
    if filtros.get('fecha_hasta'):
        query = query.filter(DenunciaWeb.fecha_registro <= filtros['fecha_hasta'])

    # Filtros de rango por días de investigación
    # Usamos el campo calculado y almacenado en la BD `dias_investigacion`
    # para que TODOS los componentes (tarjetas, gráficos, etc.) respeten
    # los filtros de días de forma consistente.
        if filtros.get('dias_desde'):
        query = query.filter(DenunciaWeb.dias_investigacion >= filtros['dias_desde'])
        if filtros.get('dias_hasta'):
        query = query.filter(DenunciaWeb.dias_investigacion <= filtros['dias_hasta'])

    if filtros.get('avance_desde'):
        query = query.filter(DenunciaWeb.avance >= filtros['avance_desde'])
    if filtros.get('avance_hasta'):
        query = query.filter(DenunciaWeb.avance <= filtros['avance_hasta'])
    
    return query


def obtener_datos_graficos(unidad_id, filtros=None):
    """
    Obtiene datos para los gráficos del dashboard con filtros.
    
    Returns:
        dict: {
            'estados': {estado: cantidad},
            'dias_investigacion': {rango: cantidad},
            'avance': {rango: cantidad},
            'opciones_filtros': {
                'departamentos': [...],
                'divisiones': [...],
                'estados': [...]
            }
        }
    """
    # Query base
    query_base = DenunciaWeb.query.filter_by(unidad_id=unidad_id)
    query_filtrada = aplicar_filtros(query_base, filtros)
    
    # 1. Gráfico de Estados - aplicar TODOS los filtros correctamente
    estados_query = query_filtrada
    denuncias_filtradas_por_dias = None  # Inicializar variable
    
    # Si hay filtros de días, necesitamos calcularlos dinámicamente
    # Obtener todas las denuncias que pasan los filtros básicos
    if filtros and (filtros.get('dias_desde') or filtros.get('dias_hasta')):
        from datetime import datetime
        from dateutil import parser
        
        # Obtener todas las denuncias que pasan los filtros básicos
        denuncias_candidatas = estados_query.all()
        denuncias_filtradas_por_dias = []
        
        for denuncia in denuncias_candidatas:
            if denuncia.fecha_registro:
                fecha_fin = denuncia.fecha_elevacion if denuncia.fecha_elevacion else datetime.utcnow()
                if isinstance(fecha_fin, str):
                    fecha_fin = parser.parse(fecha_fin)
                if isinstance(denuncia.fecha_registro, str):
                    fecha_registro = parser.parse(denuncia.fecha_registro)
                else:
                    fecha_registro = denuncia.fecha_registro
                
                delta = fecha_fin - fecha_registro
                dias = max(0, delta.days)
                
                # Aplicar filtros de días
                if filtros.get('dias_desde') and dias < filtros['dias_desde']:
                    continue
                if filtros.get('dias_hasta') and dias > filtros['dias_hasta']:
                    continue
                
                denuncias_filtradas_por_dias.append(denuncia)
        
        # Contar estados de las denuncias filtradas por días
        estados_dict = {}
        for denuncia in denuncias_filtradas_por_dias:
            if denuncia.estado_nombre:
                estados_dict[denuncia.estado_nombre] = estados_dict.get(denuncia.estado_nombre, 0) + 1
    else:
        # Si no hay filtros de días, usar query directa (más eficiente)
        estados_data = estados_query.with_entities(
            DenunciaWeb.estado_nombre,
            db.func.count(DenunciaWeb.id).label('cantidad')
        ).group_by(DenunciaWeb.estado_nombre).all()
        estados_dict = {estado: cantidad for estado, cantidad in estados_data if estado}
    
    # 2. Gráfico de Días de Investigación
    # Calcular días desde fecha_registro hasta fecha_elevacion (o fecha actual)
    # para TODAS las denuncias filtradas que tengan fecha_registro.
    from datetime import datetime
    estados_investigativos = ['ETAPA INVEST.', 'ETAPA INVEST. VINCULADA']
    dias_query = query_filtrada.filter(DenunciaWeb.fecha_registro.isnot(None))
    
    rangos_dias = {'0-100 días': 0, '100-200 días': 0, '200-300 días': 0, '+300 días': 0, 'Sin datos': 0}
    
    for denuncia in dias_query.all():
        if denuncia.fecha_registro:
            fecha_fin = denuncia.fecha_elevacion if denuncia.fecha_elevacion else datetime.utcnow()
            if isinstance(fecha_fin, str):
                from dateutil import parser
                fecha_fin = parser.parse(fecha_fin)
            if isinstance(denuncia.fecha_registro, str):
                from dateutil import parser
                fecha_registro = parser.parse(denuncia.fecha_registro)
            else:
                fecha_registro = denuncia.fecha_registro
            
            delta = fecha_fin - fecha_registro
            dias = max(0, delta.days)
            
            if dias < 100:
                rangos_dias['0-100 días'] += 1
            elif dias < 200:
                rangos_dias['100-200 días'] += 1
            elif dias < 300:
                rangos_dias['200-300 días'] += 1
            else:
                rangos_dias['+300 días'] += 1
        else:
            rangos_dias['Sin datos'] += 1
    
    dias_data = rangos_dias
    
    # 3. Gráfico de Avance
    avance_query = query_filtrada.filter(DenunciaWeb.avance.isnot(None))
    
    avance_data = {
        '10-20': avance_query.filter(DenunciaWeb.avance >= 10, DenunciaWeb.avance <= 20).count(),
        '30-50': avance_query.filter(DenunciaWeb.avance >= 30, DenunciaWeb.avance <= 50).count(),
        '60-70': avance_query.filter(DenunciaWeb.avance >= 60, DenunciaWeb.avance <= 70).count(),
        '80-100': avance_query.filter(DenunciaWeb.avance >= 80, DenunciaWeb.avance <= 100).count(),
        'Vacías': query_filtrada.filter(DenunciaWeb.avance.is_(None)).count()
    }
    
    # 4. Gráficos por Departamento, División y SINAR a Cargo
    departamentos_data = query_filtrada.with_entities(
        DenunciaWeb.departamento,
        db.func.count(DenunciaWeb.id).label('cantidad')
    ).group_by(DenunciaWeb.departamento).all()
    departamentos_dict = {d: cant for d, cant in departamentos_data if d}

    divisiones_data = query_filtrada.with_entities(
        DenunciaWeb.division,
        db.func.count(DenunciaWeb.id).label('cantidad')
    ).group_by(DenunciaWeb.division).all()
    divisiones_dict = {d: cant for d, cant in divisiones_data if d}

    secciones_data = query_filtrada.with_entities(
        DenunciaWeb.sinar_a_cargo,
        db.func.count(DenunciaWeb.id).label('cantidad')
    ).group_by(DenunciaWeb.sinar_a_cargo).all()
    secciones_dict = {s: cant for s, cant in secciones_data if s}
    
    # Opciones para filtros (valores únicos disponibles)
    # Si hay filtros de departamento, filtrar divisiones por esos departamentos
    query_opciones = DenunciaWeb.query.filter_by(unidad_id=unidad_id)
    if filtros and filtros.get('departamentos'):
        query_opciones = query_opciones.filter(DenunciaWeb.departamento.in_(filtros['departamentos']))
    if filtros and filtros.get('divisiones'):
        query_opciones = query_opciones.filter(DenunciaWeb.division.in_(filtros['divisiones']))
    
    opciones_filtros = {
        'tipos': sorted([t[0] for t in db.session.query(DenunciaWeb.tipo_origen).filter_by(unidad_id=unidad_id).distinct().all() if t[0]]),
        'departamentos': sorted([d[0] for d in db.session.query(DenunciaWeb.departamento).filter_by(unidad_id=unidad_id).distinct().all() if d[0]]),
        'divisiones': sorted([d[0] for d in query_opciones.with_entities(DenunciaWeb.division).distinct().all() if d[0]]),
        'secciones': sorted([s[0] for s in query_opciones.with_entities(DenunciaWeb.sinar_a_cargo).distinct().all() if s[0]]),
        'estados': sorted([e[0] for e in db.session.query(DenunciaWeb.estado_nombre).filter_by(unidad_id=unidad_id).distinct().all() if e[0]]),
        'actuarios': sorted([a[0] for a in db.session.query(DenunciaWeb.nombre_actuario).filter_by(unidad_id=unidad_id).distinct().all() if a[0]])
    }
    
    # Datos para tarjetas de resumen
    # Si hay filtros de días, el total debe calcularse de las denuncias filtradas por días
    if denuncias_filtradas_por_dias is not None:
        total_denuncias = len(denuncias_filtradas_por_dias)
    else:
        total_denuncias = query_filtrada.count()
    
    # Calcular días promedio de investigación (desde fecha_registro hasta fecha_elevacion o fecha actual)
    dias_promedio_query = query_filtrada.filter(
        DenunciaWeb.fecha_registro.isnot(None)
    )
    
    # Calcular días promedio manualmente
    total_dias = 0
    count_dias = 0
    for denuncia in dias_promedio_query.all():
        if denuncia.fecha_registro:
            fecha_fin = denuncia.fecha_elevacion if denuncia.fecha_elevacion else datetime.utcnow()
            if isinstance(fecha_fin, str):
                from dateutil import parser
                fecha_fin = parser.parse(fecha_fin)
            if isinstance(denuncia.fecha_registro, str):
                from dateutil import parser
                fecha_registro = parser.parse(denuncia.fecha_registro)
            else:
                fecha_registro = denuncia.fecha_registro
            
            delta = fecha_fin - fecha_registro
            dias = max(0, delta.days)
            total_dias += dias
            count_dias += 1
    
    dias_promedio = (total_dias / count_dias) if count_dias > 0 else 0
    
    # Calcular avance promedio
    avance_promedio_query = query_filtrada.filter(DenunciaWeb.avance.isnot(None))
    avance_promedio = avance_promedio_query.with_entities(
        db.func.avg(DenunciaWeb.avance)
    ).scalar() or 0
    
    # Datos de actuarios
    actuarios_query = db.session.query(
        DenunciaWeb.nombre_actuario,
        db.func.count(DenunciaWeb.id).label('cantidad')
    ).filter_by(unidad_id=unidad_id)
    
    # Aplicar filtros a actuarios
    if filtros:
        if filtros.get('tipos'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.tipo_origen.in_(filtros['tipos']))
        if filtros.get('departamentos'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.departamento.in_(filtros['departamentos']))
        if filtros.get('divisiones'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.division.in_(filtros['divisiones']))
        if filtros.get('secciones'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.sinar_a_cargo.in_(filtros['secciones']))
        if filtros.get('estados'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.estado_nombre.in_(filtros['estados']))
        if filtros.get('actuarios'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.nombre_actuario.in_(filtros['actuarios']))
        if filtros.get('fecha_desde'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.fecha_registro >= filtros['fecha_desde'])
        if filtros.get('fecha_hasta'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.fecha_registro <= filtros['fecha_hasta'])
        if filtros.get('dias_desde'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.dias_investigacion >= filtros['dias_desde'])
        if filtros.get('dias_hasta'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.dias_investigacion <= filtros['dias_hasta'])
        if filtros.get('avance_desde'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.avance >= filtros['avance_desde'])
        if filtros.get('avance_hasta'):
            actuarios_query = actuarios_query.filter(DenunciaWeb.avance <= filtros['avance_hasta'])
    
    actuarios_data = actuarios_query.filter(DenunciaWeb.nombre_actuario.isnot(None)).group_by(DenunciaWeb.nombre_actuario).all()
    actuarios_dict = {actuario: cantidad for actuario, cantidad in actuarios_data if actuario}
    
    # Resumen simplificado (solo total)
    resumen = {
        'total_denuncias': total_denuncias,
        'dias_promedio': round(float(dias_promedio), 1),
        'avance_promedio': round(float(avance_promedio), 1)
    }
    
    return {
        'estados': estados_dict,
        'dias_investigacion': dias_data,
        'avance': avance_data,
        'opciones_filtros': opciones_filtros,
        'total': total_denuncias,
        'resumen': resumen,
        'actuarios': actuarios_dict,
        'departamentos_chart': departamentos_dict,
        'divisiones_chart': divisiones_dict,
        'secciones_chart': secciones_dict
    }

