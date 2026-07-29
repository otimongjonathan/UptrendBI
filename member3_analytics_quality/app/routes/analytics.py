import json
import numpy as np
import pandas as pd
import plotly.express as px
from datetime import datetime
from flask import Blueprint, render_template, current_app
from flask_login import login_required

analytics_bp = Blueprint('analytics_bp', __name__)

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


# ── Analytics ─────────────────────────────────────────────────────────────────
@analytics_bp.route('/dataset/<int:dataset_id>/analytics')
@login_required
def analytics(dataset_id):
    from ..models import Dataset
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
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
        fc = df[col].astype(float)
        n_out = int(((fc < q1 - 1.5*iqr) | (fc > q3 + 1.5*iqr)).sum())
        outlier_data.append({'col': col, 'outliers': n_out, 'pct': round(n_out/len(df)*100, 2)})

    corr_json = None
    if len(numeric_cols) >= 2:
        fig = px.imshow(df[numeric_cols].corr(), text_auto='.2f', title='Correlation Heatmap',
                        color_continuous_scale='RdBu', zmin=-1, zmax=1)
        corr_json = chart_json(fig)

    dist_charts = []
    for i, col in enumerate(numeric_cols[:4]):
        fig = px.histogram(df, x=col, nbins=30, title=f'Distribution: {col}',
                           color_discrete_sequence=[PALETTE[i % len(PALETTE)]])
        fig.update_traces(marker_line_width=0)
        dist_charts.append({'col': col, 'json': chart_json(fig)})

    cat_charts = []
    for i, col in enumerate(cat_cols[:3]):
        vc = df[col].value_counts().head(10).reset_index()
        vc.columns = [col, 'count']
        fig = px.bar(vc, x=col, y='count', title=f'Top values: {col}',
                     color=col, color_discrete_sequence=PALETTE)
        fig.update_traces(marker_line_width=0)
        cat_charts.append({'col': col, 'json': chart_json(fig)})

    trend_json = None
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
    if numeric_cols:
        ms = max(skew_data, key=lambda x: abs(x['skew']))
        insights.append(f'"{ms["col"]}" is the most skewed (skew={ms["skew"]}) — consider log transformation.')
    if outlier_data:
        mo = max(outlier_data, key=lambda x: x['outliers'])
        if mo['outliers'] > 0:
            insights.append(f'"{mo["col"]}" has {mo["outliers"]} outliers ({mo["pct"]}% of data).')
    if len(numeric_cols) >= 2 and corr_json:
        corr_vals = df[numeric_cols].corr().abs()
        mask = ~np.eye(len(corr_vals), dtype=bool)
        pair = corr_vals.where(mask).stack().idxmax()
        val  = round(float(df[pair[0]].corr(df[pair[1]])), 3)
        insights.append(f'Strongest correlation: "{pair[0]}" & "{pair[1]}" (r={val}).')
    if cat_cols:
        hc = max(cat_cols, key=lambda c: df[c].nunique())
        insights.append(f'"{hc}" has the highest cardinality ({df[hc].nunique()} unique values).')

    return render_template('dashboard/analytics.html',
                           dataset=dataset, kpis=kpis, skew_data=skew_data,
                           outlier_data=outlier_data, corr_json=corr_json,
                           dist_charts=dist_charts, cat_charts=cat_charts,
                           trend_json=trend_json, insights=insights,
                           numeric_cols=numeric_cols, cat_cols=cat_cols)


# ── Data Quality ──────────────────────────────────────────────────────────────
@analytics_bp.route('/dataset/<int:dataset_id>/quality')
@login_required
def data_quality(dataset_id):
    from ..models import Dataset
    dataset = Dataset.query.get_or_404(dataset_id)
    df = load_df(dataset)
    total_cells  = df.shape[0] * df.shape[1]
    null_pct     = (df.isnull().sum().sum() / total_cells * 100) if total_cells else 0
    dup_pct      = (df.duplicated().sum() / len(df) * 100) if len(df) else 0
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    outlier_pct  = 0
    if numeric_cols:
        flags = []
        for col in numeric_cols:
            s = df[col].dropna().astype(float)
            if s.empty: continue
            q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
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

    return render_template('dashboard/quality.html',
                           dataset=dataset, score=score, grade=grade, color=color,
                           null_pct=round(null_pct,1), dup_pct=round(dup_pct,1),
                           outlier_pct=round(outlier_pct,1), col_profiles=col_profiles)


# ── Data Story ────────────────────────────────────────────────────────────────
@analytics_bp.route('/dataset/<int:dataset_id>/story')
@login_required
def data_story(dataset_id):
    from ..models import Dataset
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
        mask = ~np.eye(len(corr), dtype=bool)
        pair = corr.where(mask).stack().idxmax()
        val  = round(float(df[pair[0]].corr(df[pair[1]])), 3)
        strength = 'strong' if abs(val)>.7 else ('moderate' if abs(val)>.4 else 'weak')
        findings.append({'icon':'bi-diagram-3','color':'#0284c7','title':'Strongest Correlation',
            'text': f'<strong>"{pair[0]}"</strong> and <strong>"{pair[1]}"</strong> have a <strong>{strength} {"positive" if val>0 else "negative"} correlation</strong> (r={val}).'})
    if cat_cols:
        dom_col = cat_cols[0]
        top_val = df[dom_col].value_counts().index[0]
        top_pct = round(df[dom_col].value_counts().iloc[0]/len(df)*100, 1)
        findings.append({'icon':'bi-pie-chart','color':'#f59e0b','title':'Dominant Category',
            'text': f'In <strong>"{dom_col}"</strong>, the value <strong>"{top_val}"</strong> dominates at <strong>{top_pct}%</strong> ({df[dom_col].nunique()} unique values).'})

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
