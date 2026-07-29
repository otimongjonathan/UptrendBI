# Member 4 — Charts, Reports & NLQ

## Your Branch
`feature/charts-reports`

## Files to Place in the Project
| Your File | Place it at |
|---|---|
| `app/routes/reports.py` | `app/routes/reports.py` |
| `app/templates/dashboard/chart.html` | `app/templates/dashboard/chart.html` |
| `app/templates/dashboard/reports.html` | `app/templates/dashboard/reports.html` |
| `app/templates/dashboard/nlq.html` | `app/templates/dashboard/nlq.html` |
| `app/templates/dashboard/dashboard_view.html` | `app/templates/dashboard/dashboard_view.html` |
| `app/templates/dashboard/api_docs.html` | `app/templates/dashboard/api_docs.html` |

## Register Your Blueprint
In `app/__init__.py`, add inside `create_app()`:

```python
from .routes.reports import reports_bp
app.register_blueprint(reports_bp)
```

## Routes You Own
- POST /dataset/<id>/chart
- GET  /reports
- GET  /report/<id>
- POST /report/<id>/annotate
- POST /report/<id>/delete
- GET  /report/<id>/download
- POST /report/<id>/email
- GET  /dashboard/view
- GET  /api/live-stats
- GET  /api/dataset/<id>/stats
- GET  /api/docs
- GET/POST /dataset/<id>/nlq

## Git Steps
```bash
git clone https://github.com/otimongjonathan/UptrendBI.git
cd UptrendBI
git checkout -b feature/charts-reports
# copy your files into the correct locations above
git add app/routes/reports.py app/templates/dashboard/chart.html app/templates/dashboard/reports.html app/templates/dashboard/nlq.html app/templates/dashboard/dashboard_view.html app/templates/dashboard/api_docs.html
git commit -m "feat: chart builder, reports, NLQ, dashboard view, and API"
git push -u origin feature/charts-reports
```
