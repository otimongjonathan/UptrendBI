import json
import os
import pandas as pd
import numpy as np
import plotly
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, make_response
from flask_login import login_required, current_user
from flask_mail import Message
from ..models import Dataset, Report
from .. import db, mail

dashboard = Blueprint('dashboard', __name__)


def load_df(dataset):
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], dataset.filename)
    return pd.read_csv(path, engine='python', on_bad_lines='skip', encoding_errors='replace')


PALETTE = ['#f97316', '#facc15', '#22c55e', '#06b6d4', '#a855f7', '#ef4444', '#3b82f6', '#fb923c']


def chart_json(fig):
    fig.update_layout(
        template='plotly_dark',
        paper_bgcolor='#1e1e2e',
        plot_bgcolor='#1e1e2e',
        font=dict(color='#e0e0e0', size=12),
        title_font=dict(size=14, color='#ffffff'),
        margin=dict(l=20, r=20, t=45, b=20),
        legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(color='#e0e0e0')),
        xaxis=dict(gridcolor='#2a2a3e', linecolor='#444'),
        yaxis=dict(gridcolor='#2a2a3e', linecolor='#444'),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ── Data Quality Score ───────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/quality')
@login_required
def data_quality(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    total_cells = df.shape[0] * df.shape[1]
    null_pct  = (df.isnull().sum().sum() / total_cells * 100) if total_cells else 0
    dup_pct   = (df.duplicated().sum() / len(df) * 100) if len(df) else 0
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    outlier_pct = 0
    if numeric_cols:
        flags = []
        for col in numeric_cols:
            s_col = df[col].dropna().astype(float)
            if s_col.empty: continue
            q1, q3 = float(s_col.quantile(0.25)), float(s_col.quantile(0.75))
            iqr = q3 - q1
            flags.append(int(((df[col].astype(float) < q1-1.5*iqr) | (df[col].astype(float) > q3+1.5*iqr)).sum()))
        outlier_pct = sum(flags) / (len(df) * len(numeric_cols)) * 100
    score = max(0, round(100 - min(null_pct*1.5,35) - min(dup_pct*1.2,25) - min(outlier_pct*0.8,20)))
    if score >= 80:   grade, color = 'Excellent', '#22c55e'
    elif score >= 60: grade, color = 'Good',      '#84cc16'
    elif score >= 40: grade, color = 'Fair',       '#f97316'
    else:             grade, color = 'Poor',       '#ef4444'
    col_profiles = []
    for col in df.columns:
        s = df[col]
        null_c = int(s.isnull().sum())
        profile = {
            'name': col, 'dtype': str(s.dtype),
            'nulls': null_c, 'null_pct': round(null_c/len(df)*100, 1),
            'unique': int(s.nunique()), 'score': round(100 - null_c/len(df)*100),
        }
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            sf = s.dropna().astype(float)
            q1, q3 = float(sf.quantile(0.25)), float(sf.quantile(0.75))
            iqr = q3 - q1
            sf2 = s.astype(float)
            profile.update({'mean': round(float(s.mean()),2), 'std': round(float(s.std()),2),
                            'min': round(float(s.min()),2),   'max': round(float(s.max()),2),
                            'outliers': int(((sf2 < q1-1.5*iqr)|(sf2 > q3+1.5*iqr)).sum())})
        col_profiles.append(profile)
    return render_template('dashboard/quality.html',
                           dataset=dataset, score=score, grade=grade, color=color,
                           null_pct=round(null_pct,1), dup_pct=round(dup_pct,1),
                           outlier_pct=round(outlier_pct,1), col_profiles=col_profiles)


# ── Data Story Generator ─────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/story')
@login_required
def data_story(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    cat_cols     = df.select_dtypes(include='object').columns.tolist()
    total_cells  = df.shape[0] * df.shape[1]
    null_pct = (df.isnull().sum().sum() / total_cells * 100) if total_cells else 0
    dup_pct  = (df.duplicated().sum() / len(df) * 100) if len(df) else 0
    score = max(0, round(100 - min(null_pct*1.5,35) - min(dup_pct*1.2,25)))
    findings = []
    findings.append({'icon':'bi-table','color':'#f97316','title':'Dataset Overview',
        'text': f'The dataset <strong>{dataset.name}</strong> contains <strong>{df.shape[0]:,} rows</strong> and <strong>{df.shape[1]} columns</strong> — {len(numeric_cols)} numeric and {len(cat_cols)} categorical.'})
    if df.isnull().sum().sum() > 0:
        worst = df.isnull().sum().idxmax()
        findings.append({'icon':'bi-exclamation-triangle','color':'#ef4444','title':'Missing Data Alert',
            'text': f'<strong>{int(df.isnull().sum().sum()):,} missing values</strong> detected. Column <strong>"{worst}"</strong> is the worst at <strong>{round(df[worst].isnull().mean()*100,1)}%</strong> missing.'})
    else:
        findings.append({'icon':'bi-check-circle','color':'#22c55e','title':'Clean Data',
            'text': 'No missing values detected. Your dataset is complete and ready for analysis.'})
    if numeric_cols:
        most_skewed = max(numeric_cols, key=lambda c: abs(float(df[c].skew())))
        sk_val = round(float(df[most_skewed].skew()), 2)
        findings.append({'icon':'bi-bar-chart','color':'#8b5cf6','title':'Distribution Insight',
            'text': f'Column <strong>"{most_skewed}"</strong> shows the strongest skew ({sk_val}). Consider log transformation before modelling.'})
    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr().abs()
        masked = corr.where(~np.eye(len(corr), dtype=bool))
        pair = masked.stack().idxmax()
        val  = round(float(df[pair[0]].corr(df[pair[1]])), 3)
        strength = 'strong' if abs(val)>.7 else ('moderate' if abs(val)>.4 else 'weak')
        findings.append({'icon':'bi-diagram-3','color':'#0284c7','title':'Strongest Correlation',
            'text': f'<strong>"{pair[0]}"</strong> and <strong>"{pair[1]}"</strong> have a <strong>{strength} {"positive" if val>0 else "negative"} correlation</strong> (r = {val}).'})
    if cat_cols:
        dom_col = cat_cols[0]
        top_val = df[dom_col].value_counts().index[0]
        top_pct = round(df[dom_col].value_counts().iloc[0]/len(df)*100, 1)
        findings.append({'icon':'bi-pie-chart','color':'#f59e0b','title':'Dominant Category',
            'text': f'In <strong>"{dom_col}"</strong>, the value <strong>"{top_val}"</strong> dominates at <strong>{top_pct}%</strong> ({df[dom_col].nunique()} unique values).'})
    if numeric_cols:
        def _iqr_outliers(c):
            sf = df[c].dropna().astype(float)
            if sf.empty: return 0
            q1, q3 = float(sf.quantile(.25)), float(sf.quantile(.75))
            iqr = q3 - q1
            fc = df[c].astype(float)
            return int(((fc < q1-1.5*iqr)|(fc > q3+1.5*iqr)).sum())
        safe_num = [c for c in numeric_cols if not pd.api.types.is_bool_dtype(df[c])]
        worst_out = max(safe_num, key=_iqr_outliers) if safe_num else numeric_cols[0]
        n_out = _iqr_outliers(worst_out)
        if n_out > 0:
            findings.append({'icon':'bi-lightning','color':'#ef4444','title':'Outlier Detection',
                'text': f'<strong>{n_out:,} outliers</strong> detected in <strong>"{worst_out}"</strong> via IQR method. These may skew your analysis.'})
    chart_json_str = None
    if cat_cols:
        vc = df[cat_cols[0]].value_counts().head(8).reset_index()
        vc.columns = [cat_cols[0], 'count']
        chart_json_str = chart_json(px.bar(vc, x=cat_cols[0], y='count',
            title=f'Top values in "{cat_cols[0]}"', color_discrete_sequence=['#f97316']))
    elif numeric_cols:
        chart_json_str = chart_json(px.histogram(df, x=numeric_cols[0], nbins=30,
            title=f'Distribution of "{numeric_cols[0]}"', color_discrete_sequence=['#f97316']))
    return render_template('dashboard/story.html', dataset=dataset, findings=findings,
                           score=score, chart_json=chart_json_str,
                           generated_at=datetime.now().strftime('%d %B %Y, %H:%M'))


# ── Natural Language Query ────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/nlq', methods=['GET', 'POST'])
@login_required
def nlq(dataset_id):
    import re
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
            elif any(w in query for w in ['trend','over time','time series']):
                for col in df.columns:
                    try:
                        df['_dt'] = pd.to_datetime(df[col])
                        num = find_col(numeric_cols)
                        if num:
                            agg = df.groupby('_dt')[num].mean().reset_index()
                            chart_json_str = chart_json(px.line(agg, x='_dt', y=num, title=f'{num} over time', color_discrete_sequence=['#f97316']))
                            answer, matched = f'Trend of <strong>{num}</strong> over time.', True
                        df.drop(columns=['_dt'], inplace=True); break
                    except Exception:
                        if '_dt' in df.columns: df.drop(columns=['_dt'], inplace=True)
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


# ── Toggle dataset visibility ───────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/toggle-visibility', methods=['POST'])
@login_required
def toggle_visibility(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    if dataset.user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard.datasets_page'))
    dataset.is_public = not dataset.is_public
    db.session.commit()
    flash(f'"{dataset.name}" is now {"public" if dataset.is_public else "private"}.', 'success')
    return redirect(url_for('dashboard.datasets_page'))


# ── Explore community datasets ──────────────────────────────────────────────
@dashboard.route('/explore')
@login_required
def explore():
    q = request.args.get('q', '').strip()
    query = Dataset.query.filter(Dataset.user_id != current_user.id, Dataset.is_public == True)
    if q:
        query = query.filter(Dataset.name.ilike(f'%{q}%'))
    datasets = query.order_by(Dataset.uploaded_at.desc()).all()
    # attach owner username to each dataset
    from ..models import User
    owners = {u.id: u.username for u in User.query.all()}
    return render_template('dashboard/explore.html', datasets=datasets, owners=owners, q=q)


# ── Datasets listing ────────────────────────────────────────────────────────
@dashboard.route('/datasets')
@login_required
def datasets_page():
    datasets = Dataset.query.filter_by(user_id=current_user.id).order_by(Dataset.uploaded_at.desc()).all()
    return render_template('dashboard/datasets.html', datasets=datasets)


# ── Upload page ─────────────────────────────────────────────────────────────
@dashboard.route('/upload')
@login_required
def upload_page():
    return render_template('dashboard/upload.html')


# ── Home ──────────────────────────────────────────────────────────────────────
@dashboard.route('/')
@login_required
def index():
    datasets = Dataset.query.filter_by(user_id=current_user.id).order_by(Dataset.uploaded_at.desc()).all()
    reports  = Report.query.filter_by(user_id=current_user.id).order_by(Report.created_at.desc()).limit(6).all()
    total_rows = sum(d.rows for d in datasets)
    return render_template('dashboard/index.html',
                           datasets=datasets, reports=reports, total_rows=total_rows,
                           now_hour=datetime.now().hour)


# ── Dataset Explorer ──────────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>')
@login_required
def view_dataset(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    cat_cols     = df.select_dtypes(include='object').columns.tolist()

    null_counts  = df.isnull().sum()
    null_pct     = (null_counts / len(df) * 100).round(2)
    null_info    = [{'col': c, 'count': int(null_counts[c]), 'pct': float(null_pct[c])} for c in df.columns]

    summary = {
        'shape': df.shape,
        'dtypes': df.dtypes.astype(str).to_dict(),
        'null_info': null_info,
        'total_nulls': int(null_counts.sum()),
        'duplicates': int(df.duplicated().sum()),
        'describe': df.describe(include='all').fillna('').to_html(classes='table table-sm table-bordered'),
        'head': df.head(10).to_html(classes='table table-sm table-striped table-hover', index=False),
        'columns': df.columns.tolist(),
        'numeric_cols': numeric_cols,
        'cat_cols': cat_cols,
    }
    return render_template('dashboard/dataset.html', dataset=dataset, summary=summary)


# ── Analytics (Auto Insights) ─────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/analytics')
@login_required
def analytics(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    cat_cols     = df.select_dtypes(include='object').columns.tolist()

    # KPI cards
    kpis = []
    for col in numeric_cols[:6]:
        kpis.append({
            'label': col,
            'mean':  round(float(df[col].mean()), 2),
            'min':   round(float(df[col].min()),  2),
            'max':   round(float(df[col].max()),  2),
            'std':   round(float(df[col].std()),  2),
            'nulls': int(df[col].isnull().sum()),
        })

    # Skewness table
    skew_data = []
    for col in numeric_cols:
        sk = float(df[col].skew())
        skew_data.append({'col': col, 'skew': round(sk, 3),
                          'label': 'Right-skewed' if sk > 0.5 else ('Left-skewed' if sk < -0.5 else 'Normal')})

    # Outlier counts (IQR method)
    outlier_data = []
    for col in numeric_cols:
        if pd.api.types.is_bool_dtype(df[col]):
            outlier_data.append({'col': col, 'outliers': 0, 'pct': 0.0})
            continue
        sf = df[col].dropna().astype(float)
        q1, q3 = float(sf.quantile(0.25)), float(sf.quantile(0.75))
        iqr = q3 - q1
        fc = df[col].astype(float)
        n_out = int(((fc < q1 - 1.5*iqr) | (fc > q3 + 1.5*iqr)).sum())
        outlier_data.append({'col': col, 'outliers': n_out, 'pct': round(n_out/len(df)*100, 2)})

    # Correlation heatmap
    corr_json = None
    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr()
        fig  = px.imshow(corr, text_auto='.2f', title='Correlation Heatmap',
                         color_continuous_scale='RdBu', zmin=-1, zmax=1)
        corr_json = chart_json(fig)

    # Distribution charts (first 4 numeric cols)
    dist_charts = []
    for i, col in enumerate(numeric_cols[:4]):
        fig = px.histogram(df, x=col, nbins=30, title=f'Distribution: {col}',
                           color_discrete_sequence=[PALETTE[i % len(PALETTE)]])
        fig.update_traces(marker_line_width=0)
        dist_charts.append({'col': col, 'json': chart_json(fig)})

    # Top categories (first 3 cat cols)
    cat_charts = []
    for i, col in enumerate(cat_cols[:3]):
        vc = df[col].value_counts().head(10).reset_index()
        vc.columns = [col, 'count']
        fig = px.bar(vc, x=col, y='count', title=f'Top values: {col}',
                     color=col, color_discrete_sequence=PALETTE)
        fig.update_traces(marker_line_width=0)
        cat_charts.append({'col': col, 'json': chart_json(fig)})

    # Trend line (if any datetime-like column exists)
    trend_json = None
    for col in df.columns:
        try:
            df['_dt'] = pd.to_datetime(df[col])
            if numeric_cols:
                agg = df.groupby('_dt')[numeric_cols[0]].mean().reset_index()
                fig = px.line(agg, x='_dt', y=numeric_cols[0],
                              title=f'{numeric_cols[0]} over {col}',
                              color_discrete_sequence=['#f5a623'])
                fig.update_traces(line=dict(width=2.5))
                trend_json = chart_json(fig)
            df.drop(columns=['_dt'], inplace=True)
            break
        except Exception:
            if '_dt' in df.columns:
                df.drop(columns=['_dt'], inplace=True)

    # Insights text
    insights = []
    if df.isnull().sum().sum() > 0:
        worst = df.isnull().sum().idxmax()
        insights.append(f'Column "{worst}" has the most missing values ({int(df[worst].isnull().sum())} missing).')
    if numeric_cols:
        most_skewed = max(skew_data, key=lambda x: abs(x['skew']))
        insights.append(f'"{most_skewed["col"]}" is the most skewed column (skew={most_skewed["skew"]}) — consider log transformation.')
    if outlier_data:
        most_outliers = max(outlier_data, key=lambda x: x['outliers'])
        if most_outliers['outliers'] > 0:
            insights.append(f'"{most_outliers["col"]}" has {most_outliers["outliers"]} outliers ({most_outliers["pct"]}% of data).')
    if len(numeric_cols) >= 2 and corr_json:
        corr_vals = df[numeric_cols].corr().abs()
        # mask diagonal without mutating the array
        mask = ~np.eye(len(corr_vals), dtype=bool)
        masked = corr_vals.where(mask)
        max_corr = masked.stack().idxmax()
        val = round(float(df[max_corr[0]].corr(df[max_corr[1]])), 3)
        insights.append(f'Strongest correlation: "{max_corr[0]}" & "{max_corr[1]}" (r={val}).')
    if cat_cols:
        high_card = max(cat_cols, key=lambda c: df[c].nunique())
        insights.append(f'"{high_card}" has the highest cardinality ({df[high_card].nunique()} unique values).')

    return render_template('dashboard/analytics.html',
                           dataset=dataset, kpis=kpis, skew_data=skew_data,
                           outlier_data=outlier_data, corr_json=corr_json,
                           dist_charts=dist_charts, cat_charts=cat_charts,
                           trend_json=trend_json, insights=insights,
                           numeric_cols=numeric_cols, cat_cols=cat_cols)


# ── Data Cleaning ─────────────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/clean', methods=['GET', 'POST'])
@login_required
def clean_dataset(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)

    if request.method == 'POST':
        action = request.form.get('action')
        col    = request.form.get('col')
        fill_val = request.form.get('fill_value', '')

        before_rows = len(df)
        before_nulls = int(df.isnull().sum().sum())

        if action == 'drop_nulls_col' and col:
            df = df.dropna(subset=[col])
        elif action == 'drop_nulls_all':
            df = df.dropna()
        elif action == 'fill_mean' and col:
            df[col] = df[col].fillna(df[col].mean())
        elif action == 'fill_median' and col:
            df[col] = df[col].fillna(df[col].median())
        elif action == 'fill_mode' and col:
            df[col] = df[col].fillna(df[col].mode()[0])
        elif action == 'fill_value' and col and fill_val != '':
            try:
                df[col] = df[col].fillna(float(fill_val) if df[col].dtype != object else fill_val)
            except ValueError:
                df[col] = df[col].fillna(fill_val)
        elif action == 'drop_col' and col:
            df = df.drop(columns=[col])
        elif action == 'drop_duplicates':
            df = df.drop_duplicates()

        path = os.path.join(current_app.config['UPLOAD_FOLDER'], dataset.filename)
        df.to_csv(path, index=False)
        dataset.rows    = len(df)
        dataset.columns = len(df.columns)
        db.session.commit()

        after_nulls = int(df.isnull().sum().sum())
        flash(f'Done. Rows: {before_rows}→{len(df)} | Nulls: {before_nulls}→{after_nulls}', 'success')
        return redirect(url_for('dashboard.clean_dataset', dataset_id=dataset_id))

    null_info = {col: int(df[col].isnull().sum()) for col in df.columns}
    return render_template('dashboard/clean.html', dataset=dataset, df_head=df.head(8),
                           null_info=null_info, columns=df.columns.tolist(),
                           numeric_cols=df.select_dtypes(include='number').columns.tolist(),
                           shape=df.shape, duplicates=int(df.duplicated().sum()))


# ── Download Cleaned Dataset ─────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/download')
@login_required
def download_dataset(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    csv_data = df.to_csv(index=False)
    resp = make_response(csv_data)
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename="{dataset.name}_clean.csv"'
    return resp


# ── Chart Builder ─────────────────────────────────────────────────────────────
@dashboard.route('/dataset/<int:dataset_id>/chart', methods=['POST'])
@login_required
def create_chart(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    chart_type = request.form.get('chart_type')
    x_col      = request.form.get('x_col')
    y_col      = request.form.get('y_col') or None
    color_col  = request.form.get('color_col') or None
    title      = request.form.get('title', f'{chart_type} chart')

    try:
        if chart_type == 'heatmap':
            corr = df.select_dtypes(include='number').corr()
            fig  = px.imshow(corr, text_auto='.2f', title='Correlation Heatmap',
                             color_continuous_scale='RdBu', zmin=-1, zmax=1)
        elif chart_type == 'pie':
            fig = px.pie(df, names=x_col, values=y_col, title=title,
                         color_discrete_sequence=PALETTE)
        elif chart_type == 'area':
            fig = px.area(df, x=x_col, y=y_col, color=color_col, title=title,
                          color_discrete_sequence=PALETTE)
        elif chart_type == 'violin':
            fig = px.violin(df, x=color_col, y=y_col or x_col, box=True, title=title,
                            color_discrete_sequence=PALETTE)
        elif chart_type == 'funnel':
            agg = df.groupby(x_col)[y_col].sum().reset_index() if y_col else df[x_col].value_counts().reset_index()
            agg.columns = [x_col, 'value']
            fig = px.funnel(agg, x='value', y=x_col, title=title,
                            color_discrete_sequence=PALETTE)
        else:
            fn_map = {'bar': px.bar, 'line': px.line, 'scatter': px.scatter,
                      'histogram': px.histogram, 'box': px.box}
            fig = fn_map.get(chart_type, px.bar)(df, x=x_col, y=y_col, color=color_col,
                                                  title=title, color_discrete_sequence=PALETTE)

        cj = chart_json(fig)
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
@dashboard.route('/reports')
@login_required
def reports():
    datasets = Dataset.query.filter_by(user_id=current_user.id).order_by(Dataset.uploaded_at.desc()).all()
    grouped = []
    for ds in datasets:
        ds_reports = Report.query.filter_by(dataset_id=ds.id, user_id=current_user.id)\
                                 .order_by(Report.created_at.desc()).all()
        if ds_reports:
            grouped.append((ds, ds_reports))
    total = sum(len(r) for _, r in grouped)
    return render_template('dashboard/reports.html', grouped=grouped, total=total)


@dashboard.route('/report/<int:report_id>')
@login_required
def view_report(report_id):
    report = Report.query.get_or_404(report_id)
    config = json.loads(report.config)
    return render_template('dashboard/chart.html', chart_json=config.get('chart_json', '{}'),
                           title=report.title, dataset=Dataset.query.get(report.dataset_id),
                           report_id=report.id, annotations=report.annotations or '')


@dashboard.route('/report/<int:report_id>/annotate', methods=['POST'])
@login_required
def annotate_report(report_id):
    report = Report.query.get_or_404(report_id)
    report.annotations = request.form.get('annotations', '')
    db.session.commit()
    flash('Annotation saved.', 'success')
    return redirect(url_for('dashboard.view_report', report_id=report_id))


@dashboard.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    report = Report.query.get_or_404(report_id)
    db.session.delete(report)
    db.session.commit()
    flash('Report deleted.', 'success')
    return redirect(url_for('dashboard.reports'))


@dashboard.route('/report/<int:report_id>/download')
@login_required
def download_report(report_id):
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


@dashboard.route('/report/<int:report_id>/email', methods=['POST'])
@login_required
def email_report(report_id):
    report = Report.query.get_or_404(report_id)
    recipient = request.form.get('email', '').strip()
    if not recipient:
        flash('Please enter a valid email address.', 'danger')
        return redirect(url_for('dashboard.view_report', report_id=report_id))

    config = json.loads(report.config)
    cj = config.get('chart_json', '{}')
    html_body = f"""<!DOCTYPE html>
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
    try:
        msg = Message(
            subject=f'Uptrend BI Report: {report.title}',
            recipients=[recipient],
            html=f'<p>Hi,</p><p>Please find your Uptrend BI report <strong>{report.title}</strong> attached.</p><p>— Uptrend BI</p>',
        )
        msg.attach(f'{report.title.replace(" ","_")}.html', 'text/html', html_body)
        mail.send(msg)
        flash(f'Report sent to {recipient}.', 'success')
    except Exception as e:
        flash(f'Email failed: {e}', 'danger')
    return redirect(url_for('dashboard.view_report', report_id=report_id))


# ── Profile ───────────────────────────────────────────────────────────────────
@dashboard.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    from ..models import User
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_info':
            new_username = request.form.get('username', '').strip()
            new_email    = request.form.get('email', '').strip()
            if not new_username or not new_email:
                flash('Username and email cannot be empty.', 'danger')
            elif new_username != current_user.username and User.query.filter_by(username=new_username).first():
                flash('Username already taken.', 'danger')
            elif new_email != current_user.email and User.query.filter_by(email=new_email).first():
                flash('Email already in use.', 'danger')
            else:
                current_user.username = new_username
                current_user.email    = new_email
                db.session.commit()
                flash('Profile updated successfully.', 'success')
        elif action == 'change_password':
            current_pw  = request.form.get('current_password', '')
            new_pw      = request.form.get('new_password', '')
            confirm_pw  = request.form.get('confirm_password', '')
            if not current_user.check_password(current_pw):
                flash('Current password is incorrect.', 'danger')
            elif len(new_pw) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            elif new_pw != confirm_pw:
                flash('Passwords do not match.', 'danger')
            else:
                current_user.set_password(new_pw)
                db.session.commit()
                flash('Password changed successfully.', 'success')
        return redirect(url_for('dashboard.profile'))
    return render_template('dashboard/profile.html')


# ── API Docs ─────────────────────────────────────────────────────────────────
@dashboard.route('/api/docs')
@login_required
def api_docs():
    datasets = Dataset.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard/api_docs.html', datasets=datasets)


# ── Multi-Chart Dashboard View ───────────────────────────────────────────────
@dashboard.route('/dashboard/view')
@login_required
def dashboard_view():
    dataset_id = request.args.get('dataset_id', type=int)
    datasets   = Dataset.query.filter_by(user_id=current_user.id).all()
    query      = Report.query.filter_by(user_id=current_user.id)
    if dataset_id:
        query = query.filter_by(dataset_id=dataset_id)
    reports = query.order_by(Report.created_at.desc()).all()
    charts  = []
    for r in reports:
        cfg = json.loads(r.config)
        charts.append({'id': r.id, 'title': r.title, 'chart_type': r.chart_type,
                       'chart_json': cfg.get('chart_json', '{}'),
                       'created_at': r.created_at})
    return render_template('dashboard/dashboard_view.html',
                           charts=charts, datasets=datasets,
                           active_dataset_id=dataset_id)


# ── DB Connector helpers 
def _db_connect_engine(form):
    import sqlalchemy as sa
    db_type  = form.get('db_type', 'postgresql')
    host     = form.get('host', '127.0.0.1').strip()
    if host.lower() == 'localhost':
        host = '127.0.0.1'
    port     = form.get('port', '5432')
    dbname   = form.get('dbname', '')
    username = form.get('username', '')
    password = form.get('password', '').strip()
    if not password and db_type == 'postgresql':
        password = form.get('password_default', '')
    driver = 'postgresql+psycopg2' if db_type == 'postgresql' else 'mysql+pymysql'
    if host.lower() in ('localhost', '::1'):
        host = '127.0.0.1'
    conn_url = f"{driver}://{username}:{password}@{host}:{port}/{dbname}"
    connect_args = {'connect_timeout': 8} if db_type == 'postgresql' else {'connect_timeout': 8, 'charset': 'utf8mb4'}
    return sa.create_engine(conn_url, connect_args=connect_args)

def _db_load_df(form):
    import sqlalchemy as sa
    engine    = _db_connect_engine(form)
    query_sql = form.get('query', '').strip()
    with engine.connect() as conn:
        if query_sql:
            return pd.read_sql(sa.text(query_sql), conn)

        inspector = sa.inspect(engine)
        table_names = inspector.get_table_names()
        if not table_names:
            raise ValueError('No tables were found in the connected database. Add a SQL query or select a database with tables.')

        first_table = table_names[0]
        table = sa.Table(first_table, sa.MetaData(), autoload_with=engine)
        return pd.read_sql(sa.select(table).limit(200), conn)

def _db_conn_params(form):
    """Return connection params, falling back to env DATABASE_URL defaults."""
    import os, re
    db_url = os.environ.get('DATABASE_URL', '')
    # parse defaults from DATABASE_URL: driver://user:pass@host:port/dbname
    m = re.match(r'[^:]+://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+)', db_url)
    def_user, def_pass, def_host, def_port, def_db = (
        (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        if m else ('postgres', '', '127.0.0.1', '5432', '')
    )
    db_type = form.get('db_type', 'postgresql')
    default_port = def_port if db_type == 'postgresql' else form.get('port', '3306')
    return {
        'db_type':  db_type,
        'host':     form.get('host',     def_host),
        'port':     form.get('port',     default_port),
        'dbname':   form.get('dbname',   def_db),
        'username': form.get('username', def_user),
        'password': form.get('password', def_pass),
        'query':    form.get('query',    ''),
    }


# ── DB Connector — Explorer ───────────────────────────────────────────────────
@dashboard.route('/db-connect', methods=['GET', 'POST'])
@login_required
def db_connect():
    result = error = chart_json_str = None
    columns = []
    summary = None
    form = request.form

    if request.method == 'POST':
        try:
            df      = _db_load_df(form)
            numeric_cols = df.select_dtypes(include='number').columns.tolist()
            cat_cols     = df.select_dtypes(include='object').columns.tolist()
            null_counts  = df.isnull().sum()
            null_pct     = (null_counts / len(df) * 100).round(2)
            null_info    = [{'col': c, 'count': int(null_counts[c]), 'pct': float(null_pct[c])} for c in df.columns]
            columns      = df.columns.tolist()
            summary = {
                'shape':        df.shape,
                'dtypes':       df.dtypes.astype(str).to_dict(),
                'null_info':    null_info,
                'total_nulls':  int(null_counts.sum()),
                'duplicates':   int(df.duplicated().sum()),
                'describe':     df.describe(include='all').fillna('').to_html(classes='table table-sm table-bordered'),
                'head':         df.head(10).to_html(classes='table table-sm table-striped table-hover', index=False),
                'columns':      columns,
                'numeric_cols': numeric_cols,
                'cat_cols':     cat_cols,
            }
            result = df.head(200).to_html(
                classes='table table-sm table-hover table-striped mb-0', index=False, border=0)
            if numeric_cols and len(df.columns) >= 2:
                fig = px.bar(df.head(30), x=df.columns[0], y=numeric_cols[0],
                             title=f'{numeric_cols[0]} by {df.columns[0]}',
                             color_discrete_sequence=PALETTE)
                chart_json_str = chart_json(fig)
        except Exception as e:
            error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, summary=summary,
                           form=form, conn=_db_conn_params(form), active_tab='explorer')


# ── DB Connector — Analytics ──────────────────────────────────────────────────
@dashboard.route('/db-connect/analytics', methods=['POST'])
@login_required
def db_connect_analytics():
    form = request.form
    error = None
    kpis = skew_data = outlier_data = dist_charts = cat_charts = insights = []
    corr_json = trend_json = None
    try:
        df           = _db_load_df(form)
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        cat_cols     = df.select_dtypes(include='object').columns.tolist()

        kpis = []
        for col in numeric_cols[:6]:
            kpis.append({'label': col,
                         'mean':  round(float(df[col].mean()), 2),
                         'min':   round(float(df[col].min()),  2),
                         'max':   round(float(df[col].max()),  2),
                         'std':   round(float(df[col].std()),  2),
                         'nulls': int(df[col].isnull().sum())})

        skew_data = []
        for col in numeric_cols:
            sk = float(df[col].skew())
            skew_data.append({'col': col, 'skew': round(sk, 3),
                              'label': 'Right-skewed' if sk > 0.5 else ('Left-skewed' if sk < -0.5 else 'Normal')})

        outlier_data = []
        for col in numeric_cols:
            if pd.api.types.is_bool_dtype(df[col]):
                outlier_data.append({'col': col, 'outliers': 0, 'pct': 0.0}); continue
            sf = df[col].dropna().astype(float)
            q1, q3 = float(sf.quantile(0.25)), float(sf.quantile(0.75))
            iqr = q3 - q1
            fc  = df[col].astype(float)
            n   = int(((fc < q1-1.5*iqr) | (fc > q3+1.5*iqr)).sum())
            outlier_data.append({'col': col, 'outliers': n, 'pct': round(n/len(df)*100, 2)})

        if len(numeric_cols) >= 2:
            fig = px.imshow(df[numeric_cols].corr(), text_auto='.2f', title='Correlation Heatmap',
                            color_continuous_scale='RdBu', zmin=-1, zmax=1)
            corr_json = chart_json(fig)

        dist_charts = []
        for i, col in enumerate(numeric_cols[:4]):
            fig = px.histogram(df, x=col, nbins=30, title=f'Distribution: {col}',
                               color_discrete_sequence=[PALETTE[i % len(PALETTE)]])
            dist_charts.append({'col': col, 'json': chart_json(fig)})

        cat_charts = []
        for i, col in enumerate(cat_cols[:3]):
            vc = df[col].value_counts().head(10).reset_index()
            vc.columns = [col, 'count']
            fig = px.bar(vc, x=col, y='count', title=f'Top values: {col}',
                         color=col, color_discrete_sequence=PALETTE)
            cat_charts.append({'col': col, 'json': chart_json(fig)})

        for col in df.columns:
            try:
                df['_dt'] = pd.to_datetime(df[col])
                if numeric_cols:
                    agg = df.groupby('_dt')[numeric_cols[0]].mean().reset_index()
                    fig = px.line(agg, x='_dt', y=numeric_cols[0],
                                  title=f'{numeric_cols[0]} over {col}',
                                  color_discrete_sequence=['#f5a623'])
                    trend_json = chart_json(fig)
                df.drop(columns=['_dt'], inplace=True); break
            except Exception:
                if '_dt' in df.columns: df.drop(columns=['_dt'], inplace=True)

        insights = []
        if df.isnull().sum().sum() > 0:
            worst = df.isnull().sum().idxmax()
            insights.append(f'Column "{worst}" has the most missing values ({int(df[worst].isnull().sum())} missing).')
        if skew_data:
            ms = max(skew_data, key=lambda x: abs(x['skew']))
            insights.append(f'"{ms["col"]}" is the most skewed (skew={ms["skew"]}) — consider log transformation.')
        if outlier_data:
            mo = max(outlier_data, key=lambda x: x['outliers'])
            if mo['outliers'] > 0:
                insights.append(f'"{mo["col"]}" has {mo["outliers"]} outliers ({mo["pct"]}% of data).')
        if len(numeric_cols) >= 2 and corr_json:
            corr_vals = df[numeric_cols].corr().abs()
            mask      = ~np.eye(len(corr_vals), dtype=bool)
            pair      = corr_vals.where(mask).stack().idxmax()
            val       = round(float(df[pair[0]].corr(df[pair[1]])), 3)
            insights.append(f'Strongest correlation: "{pair[0]}" & "{pair[1]}" (r={val}).')
        if cat_cols:
            hc = max(cat_cols, key=lambda c: df[c].nunique())
            insights.append(f'"{hc}" has the highest cardinality ({df[hc].nunique()} unique values).')

    except Exception as e:
        error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, kpis=kpis, skew_data=skew_data,
                           outlier_data=outlier_data, corr_json=corr_json,
                           dist_charts=dist_charts, cat_charts=cat_charts,
                           trend_json=trend_json, insights=insights,
                           form=form, conn=_db_conn_params(form), active_tab='analytics')


# ── DB Connector — Quality ────────────────────────────────────────────────────
@dashboard.route('/db-connect/quality', methods=['POST'])
@login_required
def db_connect_quality():
    form  = request.form
    error = None
    score = grade = color = None
    null_pct = dup_pct = outlier_pct = 0
    col_profiles = []
    try:
        df          = _db_load_df(form)
        total_cells = df.shape[0] * df.shape[1]
        null_pct    = (df.isnull().sum().sum() / total_cells * 100) if total_cells else 0
        dup_pct     = (df.duplicated().sum() / len(df) * 100) if len(df) else 0
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        flags = []
        for col in numeric_cols:
            s = df[col].dropna().astype(float)
            if s.empty: continue
            q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
            iqr = q3 - q1
            flags.append(int(((df[col].astype(float) < q1-1.5*iqr) | (df[col].astype(float) > q3+1.5*iqr)).sum()))
        outlier_pct = sum(flags) / (len(df) * len(numeric_cols)) * 100 if numeric_cols else 0
        score = max(0, round(100 - min(null_pct*1.5,35) - min(dup_pct*1.2,25) - min(outlier_pct*0.8,20)))
        if score >= 80:   grade, color = 'Excellent', '#22c55e'
        elif score >= 60: grade, color = 'Good',      '#84cc16'
        elif score >= 40: grade, color = 'Fair',       '#f97316'
        else:             grade, color = 'Poor',       '#ef4444'
        for col in df.columns:
            s      = df[col]
            null_c = int(s.isnull().sum())
            profile = {'name': col, 'dtype': str(s.dtype),
                       'nulls': null_c, 'null_pct': round(null_c/len(df)*100, 1),
                       'unique': int(s.nunique()), 'score': round(100 - null_c/len(df)*100)}
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                sf = s.dropna().astype(float)
                q1, q3 = float(sf.quantile(0.25)), float(sf.quantile(0.75))
                iqr = q3 - q1
                sf2 = s.astype(float)
                profile.update({'mean': round(float(s.mean()),2), 'std': round(float(s.std()),2),
                                'min':  round(float(s.min()),2),  'max': round(float(s.max()),2),
                                'outliers': int(((sf2 < q1-1.5*iqr)|(sf2 > q3+1.5*iqr)).sum())})
            col_profiles.append(profile)
    except Exception as e:
        error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, score=score, grade=grade, color=color,
                           null_pct=round(null_pct,1), dup_pct=round(dup_pct,1),
                           outlier_pct=round(outlier_pct,1), col_profiles=col_profiles,
                           form=form, conn=_db_conn_params(form), active_tab='quality')


# ── DB Connector — NLQ ───────────────────────────────────────────────────────
@dashboard.route('/db-connect/nlq', methods=['POST'])
@login_required
def db_connect_nlq():
    import re
    form  = request.form
    error = None
    result_nlq = None
    numeric_cols = cat_cols = []
    try:
        df           = _db_load_df(form)
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        cat_cols     = df.select_dtypes(include='object').columns.tolist()
        nlq_query    = form.get('nlq_query', '').strip().lower()

        if nlq_query:
            chart_json_str, answer, matched = None, None, False

            def find_col(cols):
                for c in cols:
                    if c.lower() in nlq_query: return c
                return cols[0] if cols else None

            try:
                top_n = int(m.group(1)) if (m := re.search(r'top\s*(\d+)', nlq_query)) else 5
                if any(w in nlq_query for w in ['top','most','highest','largest','best']):
                    col, group = find_col(numeric_cols), find_col(cat_cols)
                    if col and group:
                        agg = df.groupby(group)[col].sum().nlargest(top_n).reset_index()
                        chart_json_str = chart_json(px.bar(agg, x=group, y=col, title=f'Top {top_n} {group} by {col}', color_discrete_sequence=['#f97316']))
                        answer, matched = f'Top {top_n} <strong>{group}</strong> by <strong>{col}</strong>.', True
                elif any(w in nlq_query for w in ['average','mean','avg']):
                    col, group = find_col(numeric_cols), find_col(cat_cols)
                    if col and group:
                        agg = df.groupby(group)[col].mean().reset_index()
                        chart_json_str = chart_json(px.bar(agg, x=group, y=col, title=f'Average {col} by {group}', color_discrete_sequence=['#8b5cf6']))
                        answer, matched = f'Average <strong>{col}</strong> by <strong>{group}</strong>.', True
                    elif col:
                        answer, matched = f'Average of <strong>{col}</strong>: <strong>{round(float(df[col].mean()),2):,}</strong>.', True
                elif any(w in nlq_query for w in ['distribution','histogram']):
                    col = find_col(numeric_cols)
                    if col:
                        chart_json_str = chart_json(px.histogram(df, x=col, nbins=30, title=f'Distribution of {col}', color_discrete_sequence=['#0284c7']))
                        answer, matched = f'Distribution of <strong>{col}</strong>.', True
                elif any(w in nlq_query for w in ['correlation','relationship']):
                    if len(numeric_cols) >= 2:
                        chart_json_str = chart_json(px.imshow(df[numeric_cols].corr(), text_auto='.2f', title='Correlation Heatmap', color_continuous_scale='RdBu', zmin=-1, zmax=1))
                        answer, matched = 'Correlation heatmap across all numeric columns.', True
                elif any(w in nlq_query for w in ['count','how many','frequency']):
                    col = find_col(cat_cols)
                    if col:
                        vc = df[col].value_counts().head(10).reset_index(); vc.columns = [col,'count']
                        chart_json_str = chart_json(px.bar(vc, x=col, y='count', title=f'Count of {col}', color_discrete_sequence=['#22c55e']))
                        answer, matched = f'Value counts for <strong>{col}</strong>.', True
                elif any(w in nlq_query for w in ['outlier','anomaly']):
                    col = find_col(numeric_cols)
                    if col:
                        sf = df[col].dropna().astype(float)
                        q1, q3 = float(sf.quantile(.25)), float(sf.quantile(.75))
                        iqr = q3 - q1
                        n = int(((df[col].astype(float)<q1-1.5*iqr)|(df[col].astype(float)>q3+1.5*iqr)).sum())
                        chart_json_str = chart_json(px.box(df, y=col, title=f'Outliers in {col}', color_discrete_sequence=['#ef4444']))
                        answer, matched = f'<strong>{n} outliers</strong> in <strong>{col}</strong>.', True
                elif any(w in nlq_query for w in ['compare','vs','scatter']):
                    if len(numeric_cols) >= 2:
                        c1, c2 = numeric_cols[0], numeric_cols[1]
                        chart_json_str = chart_json(px.scatter(df, x=c1, y=c2, color=find_col(cat_cols) if cat_cols else None, title=f'{c1} vs {c2}', color_discrete_sequence=PALETTE))
                        answer, matched = f'Scatter: <strong>{c1}</strong> vs <strong>{c2}</strong>.', True
                result_nlq = {'query': form.get('nlq_query',''), 'answer': answer, 'chart': chart_json_str, 'matched': matched}
            except Exception as ex:
                result_nlq = {'query': form.get('nlq_query',''), 'answer': f'Error: {ex}', 'chart': None, 'matched': False}
    except Exception as e:
        error = str(e)

    suggestions = [
        f'Show top 5 by {numeric_cols[0] if numeric_cols else "value"}',
        f'What is the average {numeric_cols[0] if numeric_cols else "value"}',
        f'Show distribution of {numeric_cols[0] if numeric_cols else "column"}',
        'Show correlation between columns',
        f'How many {cat_cols[0] if cat_cols else "categories"}',
        f'Show outliers in {numeric_cols[0] if numeric_cols else "column"}',
        f'Compare {numeric_cols[0] if numeric_cols else "col1"} vs {numeric_cols[1] if len(numeric_cols)>1 else "col2"}',
    ]
    return render_template('dashboard/db_connect.html',
                           error=error, result_nlq=result_nlq, suggestions=suggestions,
                           numeric_cols=numeric_cols, cat_cols=cat_cols,
                           form=form, conn=_db_conn_params(form), active_tab='nlq')


# ── DB Connector — Chart Builder ──────────────────────────────────────────────
@dashboard.route('/db-connect/chart', methods=['POST'])
@login_required
def db_connect_chart():
    form  = request.form
    error = None
    built_chart = None
    columns = numeric_cols = cat_cols = []
    try:
        df           = _db_load_df(form)
        columns      = df.columns.tolist()
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        cat_cols     = df.select_dtypes(include='object').columns.tolist()
        chart_type   = form.get('chart_type', 'bar')
        x_col        = form.get('x_col')
        y_col        = form.get('y_col') or None
        color_col    = form.get('color_col') or None
        title        = form.get('chart_title', f'{chart_type} chart')

        if chart_type == 'heatmap':
            fig = px.imshow(df[numeric_cols].corr(), text_auto='.2f', title='Correlation Heatmap',
                            color_continuous_scale='RdBu', zmin=-1, zmax=1)
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
        # Save as a report linked to a virtual dataset entry (reuse first dataset or skip)
        report = Report(title=title, chart_type=chart_type, config=cfg,
                        dataset_id=1, user_id=current_user.id)
        # Only save if at least one dataset exists
        from ..models import Dataset as DS
        first_ds = DS.query.filter_by(user_id=current_user.id).first()
        if first_ds:
            report.dataset_id = first_ds.id
            db.session.add(report)
            db.session.commit()
            flash('Chart saved to reports.', 'success')
        built_chart = {'json': cj, 'title': title}
    except Exception as e:
        error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, built_chart=built_chart,
                           columns=columns, numeric_cols=numeric_cols, cat_cols=cat_cols,
                           form=form, conn=_db_conn_params(form), active_tab='chart')


# ── API: live stats refresh ───────────────────────────────────────────────────
@dashboard.route('/api/live-stats')
@login_required
def api_live_stats():
    datasets = Dataset.query.filter_by(user_id=current_user.id).all()
    reports  = Report.query.filter_by(user_id=current_user.id).all()
    return jsonify({
        'datasets': len(datasets),
        'reports':  len(reports),
        'total_rows': sum(d.rows for d in datasets),
    })
@dashboard.route('/api/dataset/<int:dataset_id>/stats')
@login_required
def api_stats(dataset_id):
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    stats = {}
    for col in numeric_cols:
        stats[col] = {
            'mean':   round(float(df[col].mean()), 4),
            'median': round(float(df[col].median()), 4),
            'std':    round(float(df[col].std()), 4),
            'min':    round(float(df[col].min()), 4),
            'max':    round(float(df[col].max()), 4),
            'nulls':  int(df[col].isnull().sum()),
        }
    return jsonify({'dataset': dataset.name, 'rows': dataset.rows,
                    'columns': dataset.columns, 'stats': stats})
