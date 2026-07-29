import json
import re
import numpy as np
import pandas as pd
import plotly.express as px
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

db_connector_bp = Blueprint('db_connector_bp', __name__)

PALETTE = ['#f97316', '#facc15', '#22c55e', '#06b6d4', '#a855f7', '#ef4444', '#3b82f6', '#fb923c']


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


# ── Helpers ───────────────────────────────────────────────────────────────────
def _db_connect_engine(form):
    import sqlalchemy as sa
    db_type  = form.get('db_type', 'postgresql')
    host     = form.get('host', '127.0.0.1').strip()
    if host.lower() in ('localhost', '::1'):
        host = '127.0.0.1'
    port     = form.get('port', '5432')
    dbname   = form.get('dbname', '')
    username = form.get('username', '')
    password = form.get('password', '').strip()
    if not password and db_type == 'postgresql':
        password = form.get('password_default', '')
    driver = 'postgresql+psycopg2' if db_type == 'postgresql' else 'mysql+pymysql'
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
        inspector   = sa.inspect(engine)
        table_names = inspector.get_table_names()
        if not table_names:
            raise ValueError('No tables found in the connected database.')
        table = sa.Table(table_names[0], sa.MetaData(), autoload_with=engine)
        return pd.read_sql(sa.select(table).limit(200), conn)


def _db_conn_params(form):
    import os
    db_url = os.environ.get('DATABASE_URL', '')
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


# ── Explorer ──────────────────────────────────────────────────────────────────
@db_connector_bp.route('/db-connect', methods=['GET', 'POST'])
@login_required
def db_connect():
    result = error = chart_json_str = None
    columns = []
    summary = None
    form = request.form

    if request.method == 'POST':
        try:
            df           = _db_load_df(form)
            numeric_cols = df.select_dtypes(include='number').columns.tolist()
            cat_cols     = df.select_dtypes(include='object').columns.tolist()
            null_counts  = df.isnull().sum()
            null_pct     = (null_counts / len(df) * 100).round(2)
            null_info    = [{'col': c, 'count': int(null_counts[c]), 'pct': float(null_pct[c])} for c in df.columns]
            columns      = df.columns.tolist()
            summary = {
                'shape': df.shape, 'dtypes': df.dtypes.astype(str).to_dict(),
                'null_info': null_info, 'total_nulls': int(null_counts.sum()),
                'duplicates': int(df.duplicated().sum()),
                'describe': df.describe(include='all').fillna('').to_html(classes='table table-sm table-bordered'),
                'head': df.head(10).to_html(classes='table table-sm table-striped table-hover', index=False),
                'columns': columns, 'numeric_cols': numeric_cols, 'cat_cols': cat_cols,
            }
            result = df.head(200).to_html(classes='table table-sm table-hover table-striped mb-0', index=False, border=0)
            if numeric_cols and len(df.columns) >= 2:
                fig = px.bar(df.head(30), x=df.columns[0], y=numeric_cols[0],
                             title=f'{numeric_cols[0]} by {df.columns[0]}', color_discrete_sequence=PALETTE)
                chart_json_str = chart_json(fig)
        except Exception as e:
            error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, summary=summary,
                           form=form, conn=_db_conn_params(form), active_tab='explorer')


# ── Analytics ─────────────────────────────────────────────────────────────────
@db_connector_bp.route('/db-connect/analytics', methods=['POST'])
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

        kpis = [{'label': col, 'mean': round(float(df[col].mean()),2), 'min': round(float(df[col].min()),2),
                 'max': round(float(df[col].max()),2), 'std': round(float(df[col].std()),2),
                 'nulls': int(df[col].isnull().sum())} for col in numeric_cols[:6]]

        skew_data = [{'col': col, 'skew': round(float(df[col].skew()),3),
                      'label': 'Right-skewed' if float(df[col].skew())>0.5 else ('Left-skewed' if float(df[col].skew())<-0.5 else 'Normal')}
                     for col in numeric_cols]

        outlier_data = []
        for col in numeric_cols:
            if pd.api.types.is_bool_dtype(df[col]):
                outlier_data.append({'col': col, 'outliers': 0, 'pct': 0.0}); continue
            sf = df[col].dropna().astype(float)
            q1, q3 = float(sf.quantile(0.25)), float(sf.quantile(0.75))
            iqr = q3 - q1
            n = int(((df[col].astype(float) < q1-1.5*iqr) | (df[col].astype(float) > q3+1.5*iqr)).sum())
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
                    fig = px.line(agg, x='_dt', y=numeric_cols[0], title=f'{numeric_cols[0]} over {col}',
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
            mask = ~np.eye(len(corr_vals), dtype=bool)
            pair = corr_vals.where(mask).stack().idxmax()
            val  = round(float(df[pair[0]].corr(df[pair[1]])), 3)
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


# ── Quality ───────────────────────────────────────────────────────────────────
@db_connector_bp.route('/db-connect/quality', methods=['POST'])
@login_required
def db_connect_quality():
    form  = request.form
    error = None
    score = grade = color = None
    null_pct = dup_pct = outlier_pct = 0
    col_profiles = []
    try:
        df           = _db_load_df(form)
        total_cells  = df.shape[0] * df.shape[1]
        null_pct     = (df.isnull().sum().sum() / total_cells * 100) if total_cells else 0
        dup_pct      = (df.duplicated().sum() / len(df) * 100) if len(df) else 0
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
            profile = {'name': col, 'dtype': str(s.dtype), 'nulls': null_c,
                       'null_pct': round(null_c/len(df)*100, 1), 'unique': int(s.nunique()),
                       'score': round(100 - null_c/len(df)*100)}
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


# ── NLQ ───────────────────────────────────────────────────────────────────────
@db_connector_bp.route('/db-connect/nlq', methods=['POST'])
@login_required
def db_connect_nlq():
    form  = request.form
    error = None
    result_nlq   = None
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
        'Show correlation between columns',
        f'How many {cat_cols[0] if cat_cols else "categories"}',
    ]
    return render_template('dashboard/db_connect.html',
                           error=error, result_nlq=result_nlq, suggestions=suggestions,
                           numeric_cols=numeric_cols, cat_cols=cat_cols,
                           form=form, conn=_db_conn_params(form), active_tab='nlq')


# ── Chart Builder ─────────────────────────────────────────────────────────────
@db_connector_bp.route('/db-connect/chart', methods=['POST'])
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

        from ..models import Dataset as DS, Report
        from .. import db
        first_ds = DS.query.filter_by(user_id=current_user.id).first()
        if first_ds:
            report = Report(title=title, chart_type=chart_type, config=cfg,
                            dataset_id=first_ds.id, user_id=current_user.id)
            db.session.add(report)
            db.session.commit()
        built_chart = {'json': cj, 'title': title}
    except Exception as e:
        error = str(e)

    return render_template('dashboard/db_connect.html',
                           error=error, built_chart=built_chart,
                           columns=columns, numeric_cols=numeric_cols, cat_cols=cat_cols,
                           form=form, conn=_db_conn_params(form), active_tab='chart')
