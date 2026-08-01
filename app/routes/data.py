import os
import uuid
import pandas as pd
from flask import Blueprint, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from ..models import Dataset
from .. import db

data = Blueprint('data', __name__, url_prefix='/data')

ALLOWED_EXTENSIONS = {'csv'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _db_load_df(form):
    from .dashboard import _db_load_df as dashboard_db_load_df
    return dashboard_db_load_df(form)


@data.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files.get('file')
    name = request.form.get('name', '').strip()
    if not file or not allowed_file(file.filename):
        flash('Please upload a valid CSV file.', 'danger')
        return redirect(url_for('dashboard.index'))

    filename = secure_filename(file.filename)
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    df = pd.read_csv(save_path, engine='python', on_bad_lines='skip', encoding_errors='replace')
    is_public = request.form.get('visibility') == 'public'
    dataset = Dataset(
        name=name or filename,
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        is_public=is_public,
        user_id=current_user.id
    )
    db.session.add(dataset)
    db.session.commit()
    flash(f'Dataset "{dataset.name}" uploaded successfully ({dataset.rows} rows, {dataset.columns} columns).', 'success')
    return redirect(url_for('dashboard.view_dataset', dataset_id=dataset.id))


@data.route('/export-from-db', methods=['POST'])
@login_required
def export_from_db():
    form = request.form
    name = form.get('name', '').strip()
    if not name:
        name = form.get('dbname', '').strip() or 'database_export'

    try:
        df = _db_load_df(form)
    except Exception as exc:
        flash(f'Unable to load data from the database: {exc}', 'danger')
        return redirect(url_for('dashboard.db_connect'))

    if df.empty:
        flash('The selected query returned no rows, so nothing was exported.', 'warning')
        return redirect(url_for('dashboard.db_connect'))

    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
    filename = secure_filename(f"{name}_{uuid.uuid4().hex[:8]}.csv")
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    df.to_csv(save_path, index=False)

    is_public = form.get('visibility') == 'public'
    dataset = Dataset(
        name=name,
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        is_public=is_public,
        user_id=current_user.id,
    )
    db.session.add(dataset)
    db.session.commit()

    flash(f'Dataset "{dataset.name}" was saved successfully ({dataset.rows} rows, {dataset.columns} columns).', 'success')
    return redirect(url_for('dashboard.view_dataset', dataset_id=dataset.id))


@data.route('/delete/<int:dataset_id>', methods=['POST'])
@login_required
def delete(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], dataset.filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    db.session.delete(dataset)
    db.session.commit()
    flash('Dataset deleted.', 'success')
    return redirect(url_for('dashboard.index'))
