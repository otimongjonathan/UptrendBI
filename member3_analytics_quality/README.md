# Member 3 — Analytics & Quality

## Your Branch
`feature/analytics-quality`

## Files to Place in the Project
| Your File | Place it at |
|---|---|
| `app/routes/analytics.py` | `app/routes/analytics.py` |
| `app/templates/dashboard/analytics.html` | `app/templates/dashboard/analytics.html` |
| `app/templates/dashboard/quality.html` | `app/templates/dashboard/quality.html` |
| `app/templates/dashboard/story.html` | `app/templates/dashboard/story.html` |

## Register Your Blueprint
In `app/__init__.py`, add inside `create_app()`:

```python
from .routes.analytics import analytics_bp
app.register_blueprint(analytics_bp)
```

## Routes You Own
- GET /dataset/<id>/analytics
- GET /dataset/<id>/quality
- GET /dataset/<id>/story

## Git Steps
```bash
git clone https://github.com/otimongjonathan/UptrendBI.git
cd UptrendBI
git checkout -b feature/analytics-quality
# copy your files into the correct locations above
git add app/routes/analytics.py app/templates/dashboard/analytics.html app/templates/dashboard/quality.html app/templates/dashboard/story.html
git commit -m "feat: analytics, data quality, and data story"
git push -u origin feature/analytics-quality
```
