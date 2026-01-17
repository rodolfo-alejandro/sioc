"""
Rutas de DataLab
"""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.blueprints.datalab import bp
from app.blueprints.datalab.forms import UploadDatasetForm
from app.blueprints.datalab.services import process_uploaded_file, get_user_datasets, get_dataset_by_id
from app.services.rbac import require_permission
from app.services.audit import audit_log


@bp.route('/upload', methods=['GET', 'POST'])
@login_required
@require_permission('DATALAB_UPLOAD')
def upload():
    """Subir archivo al DataLab"""
    form = UploadDatasetForm()
    
    if form.validate_on_submit():
        dataset, error = process_uploaded_file(
            file=form.file.data,
            name=form.name.data,
            unidad_id=current_user.unidad_id,
            user_id=current_user.id
        )
        
        if dataset:
            flash(f'Dataset "{dataset.name}" subido correctamente ({dataset.rows_count} filas, {dataset.columns_count} columnas)', 'success')
            return redirect(url_for('datalab.dataset_view', dataset_id=dataset.id))
        else:
            flash(error, 'danger')
    
    return render_template('datalab/upload.html', form=form)


@bp.route('/datasets')
@login_required
@require_permission('DATALAB_VIEW')
def datasets():
    """Lista de datasets"""
    datasets_list = get_user_datasets(current_user.id, current_user.unidad_id).all()
    
    # Búsqueda
    search = request.args.get('search', '')
    if search:
        datasets_list = [d for d in datasets_list if search.lower() in d.name.lower()]
    
    return render_template('datalab/datasets.html', datasets=datasets_list, search=search)


@bp.route('/datasets/<int:dataset_id>')
@login_required
@require_permission('DATALAB_VIEW')
def dataset_view(dataset_id):
    """Vista detallada de un dataset"""
    dataset = get_dataset_by_id(dataset_id, current_user.unidad_id)
    
    if not dataset:
        flash('Dataset no encontrado o sin permisos', 'danger')
        return redirect(url_for('datalab.datasets'))
    
    # Auditoría
    audit_log('DATASET_VIEWED', f'Dataset {dataset.name} visualizado')
    
    # Obtener datos
    preview = dataset.get_preview()
    profile = dataset.get_profile()
    charts = dataset.get_charts()
    
    return render_template(
        'datalab/dataset_view.html',
        dataset=dataset,
        preview=preview,
        profile=profile,
        charts=charts
    )

