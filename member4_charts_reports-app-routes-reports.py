import json
import re
import numpy as np
import pandas as pd
import plotly.express as px
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, make_response
from flask_login import login_required, current_user
from flask_mail import Message

reports_bp = Blueprint('reports_bp', __name__)

PALETTE = ['#f97316', '#facc15', '#22c55e', '#06b6d4', '#a855f7', '#ef4444', '#3b82f6', '#fb923c']


def load_df(dataset):
    import os
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], dataset.filename)
    return pd.read_csv(path, engine='python', on_bad_lines='skip', encoding_errors='replace')


def chart_json(fig):
    import plotly
    fig.update_layout(
        template='plotly_dark', paper_bgcolor='#1e1e2e', plot_bgcolor='#1e1e2e',
        font=dict(color='#e0e0e0', size=12), title_font=dict(size=14, color='#ffffff'),
        margin=dict(l=20, r=20, t=45, b=20),
        legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(color='#e0e0e0')),
        xaxis=dict(gridcolor='#2a2a3e', linecolor='#444'),
        yaxis=dict(gridcolor='#2a2a3e', linecolor='#444'),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ── NLQ ───────────────────────────────────────────────────────────────────────
@reports_bp.route('/dataset/<int:dataset_id>/nlq', methods=['GET', 'POST'])
@login_required
def nlq(dataset_id):
    from ..models import Dataset
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    cat_cols     = df.select_dtypes(include='object').columns.tolist()
    result = None

    if request.method == 'POST':
        query = request.form.get('query', '').strip().lower()
        chart_json_str, answer, matched = None, None, False

        def find_col(cols):
            for c in cols:
                if c.lower() in query: return c
            return cols[0] if cols else None

        try:
            top_n = int(m.group(1)) if (m := re.search(r'top\s*(\d+)', query)) else 5

            if any(w in query for w in ['top','most','highest','largest','best']):
                col, group = find_col(numeric_cols), find_col(cat_cols)
                if col and group:
                    agg = df.groupby(group)[col].sum().nlargest(top_n).reset_index()
                    chart_json_str = chart_json(px.bar(agg, x=group, y=col, title=f'Top {top_n} {group} by {col}', color_discrete_sequence=['#f97316']))
                    answer, matched = f'Top {top_n} <strong>{group}</strong> by <strong>{col}</strong>.', True
            elif any(w in query for w in ['bottom','lowest','least','worst','smallest']):
                col, group = find_col(numeric_cols), find_col(cat_cols)
                if col and group:
                    agg = df.groupby(group)[col].sum().nsmallest(top_n).reset_index()
                    chart_json_str = chart_json(px.bar(agg, x=group, y=col, title=f'Bottom {top_n} {group} by {col}', color_discrete_sequence=['#ef4444']))
                    answer, matched = f'Bottom {top_n} <strong>{group}</strong> by <strong>{col}</strong>.', True
            elif any(w in query for w in ['average','mean','avg']):
                col, group = find_col(numeric_cols), find_col(cat_cols)
                if col and group:
                    agg = df.groupby(group)[col].mean().reset_index()
                    chart_json_str = chart_json(px.bar(agg, x=group, y=col, title=f'Average {col} by {group}', color_discrete_sequence=['#8b5cf6']))
                    answer, matched = f'Average <strong>{col}</strong> by <strong>{group}</strong>.', True
                elif col:
                    answer, matched = f'Average of <strong>{col}</strong> is <strong>{round(float(df[col].mean()),2):,}</strong>.', True
            elif any(w in query for w in ['distribution','spread','histogram']):
                col = find_col(numeric_cols)
                if col:
                    chart_json_str = chart_json(px.histogram(df, x=col, nbins=30, title=f'Distribution of {col}', color_discrete_sequence=['#0284c7']))
                    answer, matched = f'Distribution of <strong>{col}</strong>.', True
            elif any(w in query for w in ['correlation','correlate','relationship']):
                if len(numeric_cols) >= 2:
                    chart_json_str = chart_json(px.imshow(df[numeric_cols].corr(), text_auto='.2f', title='Correlation Heatmap', color_continuous_scale='RdBu', zmin=-1, zmax=1))
                    answer, matched = 'Correlation heatmap across all numeric columns.', True
            elif any(w in query for w in ['count','how many','frequency','breakdown']):
                col = find_col(cat_cols)
                if col:
                    vc = df[col].value_counts().head(10).reset_index(); vc.columns = [col,'count']
                    chart_json_str = chart_json(px.bar(vc, x=col, y='count', title=f'Count of {col}', color_discrete_sequence=['#22c55e']))
                    answer, matched = f'Value counts for <strong>{col}</strong>.', True
            elif any(w in query for w in ['missing','null','empty']):
                total_null = int(df.isnull().sum().sum())
                worst = df.isnull().sum().idxmax()
                answer = f'Total missing: <strong>{total_null:,}</strong>. Worst column: <strong>"{worst}"</strong> ({int(df[worst].isnull().sum())}).'
                matched = True
            elif any(w in query for w in ['outlier','anomaly','anomalies']):
                col = find_col(numeric_cols)
                if col:
                    sf = df[col].dropna().astype(float)
                    q1, q3 = float(sf.quantile(.25)), float(sf.quantile(.75))
                    iqr = q3 - q1
                    fc = df[col].astype(float)
                    n = int(((fc<q1-1.5*iqr)|(fc>q3+1.5*iqr)).sum())
                    chart_json_str = chart_json(px.box(df, y=col, title=f'Outliers in {col}', color_discrete_sequence=['#ef4444']))
                    answer, matched = f'<strong>{n} outliers</strong> in <strong>{col}</strong>.', True
            elif any(w in query for w in ['compare','vs','versus','scatter']):
                if len(numeric_cols) >= 2:
                    c1, c2 = numeric_cols[0], numeric_cols[1]
                    for c in numeric_cols:
                        if c.lower() in query: c1 = c; break
                    for c in numeric_cols:
                        if c.lower() in query and c != c1: c2 = c; break
                    chart_json_str = chart_json(px.scatter(df, x=c1, y=c2, color=find_col(cat_cols) if cat_cols else None, title=f'{c1} vs {c2}', color_discrete_sequence=PALETTE))
                    answer, matched = f'Scatter: <strong>{c1}</strong> vs <strong>{c2}</strong>.', True

            result = {'query': request.form.get('query',''), 'answer': answer, 'chart': chart_json_str, 'matched': matched}
        except Exception as e:
            result = {'query': request.form.get('query',''), 'answer': f'Error: {e}', 'chart': None, 'matched': False}

    suggestions = [
        f'Show top 5 by {numeric_cols[0] if numeric_cols else "value"}',
        f'What is the average {numeric_cols[0] if numeric_cols else "value"}',
        f'Show distribution of {numeric_cols[0] if numeric_cols else "column"}',
        'Show correlation between columns',
        f'How many {cat_cols[0] if cat_cols else "categories"}',
        f'Show outliers in {numeric_cols[0] if numeric_cols else "column"}',
        f'Compare {numeric_cols[0] if numeric_cols else "col1"} vs {numeric_cols[1] if len(numeric_cols)>1 else "col2"}',
        'How many missing values',
    ]
    return render_template('dashboard/nlq.html', dataset=dataset, result=result,
                           suggestions=suggestions, numeric_cols=numeric_cols, cat_cols=cat_cols)


# ── Chart Builder ─────────────────────────────────────────────────────────────
@reports_bp.route('/dataset/<int:dataset_id>/chart', methods=['POST'])
@login_required
def create_chart(dataset_id):
    from ..models import Dataset, Report
    from .. import db
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    chart_type = request.form.get('chart_type')
    x_col      = request.form.get('x_col')
    y_col      = request.form.get('y_col') or None
    color_col  = request.form.get('color_col') or None
    title      = request.form.get('title', f'{chart_type} chart')

    try:
        if chart_type == 'heatmap':
            fig = px.imshow(df.select_dtypes(include='number').corr(), text_auto='.2f',
                            title='Correlation Heatmap', color_continuous_scale='RdBu', zmin=-1, zmax=1)
        elif chart_type == 'pie':
            fig = px.pie(df, names=x_col, values=y_col, title=title, color_discrete_sequence=PALETTE)
        elif chart_type == 'area':
            fig = px.area(df, x=x_col, y=y_col, color=color_col, title=title, color_discrete_sequence=PALETTE)
        elif chart_type == 'violin':
            fig = px.violin(df, x=color_col, y=y_col or x_col, box=True, title=title, color_discrete_sequence=PALETTE)
        elif chart_type == 'funnel':
            agg = df.groupby(x_col)[y_col].sum().reset_index() if y_col else df[x_col].value_counts().reset_index()
            agg.columns = [x_col, 'value']
            fig = px.funnel(agg, x='value', y=x_col, title=title, color_discrete_sequence=PALETTE)
        else:
            fn_map = {'bar': px.bar, 'line': px.line, 'scatter': px.scatter, 'histogram': px.histogram, 'box': px.box}
            fig = fn_map.get(chart_type, px.bar)(df, x=x_col, y=y_col, color=color_col, title=title, color_discrete_sequence=PALETTE)

        cj  = chart_json(fig)
        cfg = json.dumps({'x': x_col, 'y': y_col, 'color': color_col, 'chart_json': cj})
        report = Report(title=title, chart_type=chart_type, config=cfg,
                        dataset_id=dataset_id, user_id=current_user.id)
        db.session.add(report)
        db.session.commit()
        flash('Chart saved to reports.', 'success')
        return render_template('dashboard/chart.html', chart_json=cj, title=title, dataset=dataset, report_id=report.id)
    except Exception as e:
        flash(f'Chart error: {e}', 'danger')
        return redirect(url_for('dashboard.view_dataset', dataset_id=dataset_id))


# ── Reports ───────────────────────────────────────────────────────────────────
@reports_bp.route('/reports')
@login_required
def reports():
    from ..models import Dataset, Report
    datasets = Dataset.query.filter_by(user_id=current_user.id).order_by(Dataset.uploaded_at.desc()).all()
    grouped = []
    for ds in datasets:
        ds_reports = Report.query.filter_by(dataset_id=ds.id, user_id=current_user.id)\
                                 .order_by(Report.created_at.desc()).all()
        if ds_reports:
            grouped.append((ds, ds_reports))
    total = sum(len(r) for _, r in grouped)
    return render_template('dashboard/reports.html', grouped=grouped, total=total)


@reports_bp.route('/report/<int:report_id>')
@login_required
def view_report(report_id):
    from ..models import Report, Dataset
    report = Report.query.get_or_404(report_id)
    config = json.loads(report.config)
    return render_template('dashboard/chart.html', chart_json=config.get('chart_json', '{}'),
                           title=report.title, dataset=Dataset.query.get(report.dataset_id),
                           report_id=report.id, annotations=report.annotations or '')


@reports_bp.route('/report/<int:report_id>/annotate', methods=['POST'])
@login_required
def annotate_report(report_id):
    from ..models import Report
    from .. import db
    report = Report.query.get_or_404(report_id)
    report.annotations = request.form.get('annotations', '')
    db.session.commit()
    flash('Annotation saved.', 'success')
    return redirect(url_for('reports_bp.view_report', report_id=report_id))


@reports_bp.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    from ..models import Report
    from .. import db
    report = Report.query.get_or_404(report_id)
    db.session.delete(report)
    db.session.commit()
    flash('Report deleted.', 'success')
    return redirect(url_for('reports_bp.reports'))


@reports_bp.route('/report/<int:report_id>/download')
@login_required
def download_report(report_id):
    from ..models import Report
    report = Report.query.get_or_404(report_id)
    config = json.loads(report.config)
    cj = config.get('chart_json', '{}')
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>{report.title}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>body{{margin:0;background:#1c1917}}#chart{{width:100vw;height:100vh}}</style>
</head><body>
<div id="chart"></div>
<script>
const d = {cj};
Plotly.newPlot('chart', d.data, d.layout, {{responsive:true}});
</script>
</body></html>"""
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html'
    resp.headers['Content-Disposition'] = f'attachment; filename="{report.title.replace(" ","_")}.html"'
    return resp


@reports_bp.route('/report/<int:report_id>/email', methods=['POST'])
@login_required
def email_report(report_id):
    from ..models import Report
    from .. import mail
    report = Report.query.get_or_404(report_id)
    recipient = request.form.get('email', '').strip()
    if not recipient:
        flash('Please enter a valid email address.', 'danger')
        return redirect(url_for('reports_bp.view_report', report_id=report_id))
    config = json.loads(report.config)
    cj = config.get('chart_json', '{}')
    html_body = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><title>{report.title}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>body{{margin:0;background:#1c1917}}#chart{{width:100vw;height:100vh}}</style>
</head><body>
<div id="chart"></div>
<script>const d = {cj}; Plotly.newPlot('chart', d.data, d.layout, {{responsive:true}});</script>
</body></html>"""
    try:
        msg = Message(subject=f'Uptrend BI Report: {report.title}', recipients=[recipient],
                      html=f'<p>Hi,</p><p>Please find your Uptrend BI report <strong>{report.title}</strong> attached.</p><p>— Uptrend BI</p>')
        msg.attach(f'{report.title.replace(" ","_")}.html', 'text/html', html_body)
        mail.send(msg)
        flash(f'Report sent to {recipient}.', 'success')
    except Exception as e:
        flash(f'Email failed: {e}', 'danger')
    return redirect(url_for('reports_bp.view_report', report_id=report_id))


# ── Multi-Chart Dashboard View ────────────────────────────────────────────────
@reports_bp.route('/dashboard/view')
@login_required
def dashboard_view():
    from ..models import Dataset, Report
    dataset_id = request.args.get('dataset_id', type=int)
    datasets   = Dataset.query.filter_by(user_id=current_user.id).all()
    query      = Report.query.filter_by(user_id=current_user.id)
    if dataset_id:
        query = query.filter_by(dataset_id=dataset_id)
    reports_list = query.order_by(Report.created_at.desc()).all()
    charts = []
    for r in reports_list:
        cfg = json.loads(r.config)
        charts.append({'id': r.id, 'title': r.title, 'chart_type': r.chart_type,
                       'chart_json': cfg.get('chart_json', '{}'), 'created_at': r.created_at})
    return render_template('dashboard/dashboard_view.html',
                           charts=charts, datasets=datasets, active_dataset_id=dataset_id)


# ── API ───────────────────────────────────────────────────────────────────────
@reports_bp.route('/api/live-stats')
@login_required
def api_live_stats():
    from ..models import Dataset, Report
    datasets = Dataset.query.filter_by(user_id=current_user.id).all()
    reports_list = Report.query.filter_by(user_id=current_user.id).all()
    return jsonify({'datasets': len(datasets), 'reports': len(reports_list),
                    'total_rows': sum(d.rows for d in datasets)})


@reports_bp.route('/api/dataset/<int:dataset_id>/stats')
@login_required
def api_stats(dataset_id):
    from ..models import Dataset
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    stats = {}
    for col in numeric_cols:
        stats[col] = {'mean': round(float(df[col].mean()), 4), 'median': round(float(df[col].median()), 4),
                      'std':  round(float(df[col].std()),  4), 'min':    round(float(df[col].min()),    4),
                      'max':  round(float(df[col].max()),  4), 'nulls':  int(df[col].isnull().sum())}
    return jsonify({'dataset': dataset.name, 'rows': dataset.rows, 'columns': dataset.columns, 'stats': stats})


# ── API Docs ──────────────────────────────────────────────────────────────────
@reports_bp.route('/api/docs')
@login_required
def api_docs():
    from ..models import Dataset
    datasets = Dataset.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard/api_docs.html', datasets=datasets)
