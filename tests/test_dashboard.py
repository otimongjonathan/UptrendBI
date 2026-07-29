import os
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app, db
from app.models import Dataset, Report, User

SAMPLE_DF = pd.DataFrame({
    'city':   ['Nairobi', 'Kampala', 'Dar es Salaam', 'Kigali', 'Addis Ababa'],
    'sales':  [120, 80, 200, 60, 150],
    'profit': [30, 20, 55, 10, 45],
})


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(TESTING=True, UPLOAD_FOLDER=self.tmpdir.name)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.user = User(username='tester', email='tester@example.com')
        self.user.set_password('secret123')
        db.session.add(self.user)
        db.session.commit()

        # Create a real CSV so load_df works without mocking
        csv_path = os.path.join(self.tmpdir.name, 'sample.csv')
        SAMPLE_DF.to_csv(csv_path, index=False)
        self.dataset = Dataset(
            name='Sample', filename='sample.csv',
            rows=len(SAMPLE_DF), columns=len(SAMPLE_DF.columns),
            user_id=self.user.id,
        )
        db.session.add(self.dataset)
        db.session.commit()

        self.client = self.app.test_client()
        self.client.post('/login', data={'email': 'tester@example.com', 'password': 'secret123'})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tmpdir.cleanup()

    # ── Index / Home ──────────────────────────────────────────────────────────

    def test_index_loads(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)

    # ── Dataset views ─────────────────────────────────────────────────────────

    def test_view_dataset(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Sample', resp.data)

    def test_view_dataset_404(self):
        resp = self.client.get('/dataset/9999')
        self.assertEqual(resp.status_code, 404)

    def test_datasets_page(self):
        resp = self.client.get('/datasets')
        self.assertEqual(resp.status_code, 200)

    # ── Analytics ─────────────────────────────────────────────────────────────

    def test_analytics_loads(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}/analytics')
        self.assertEqual(resp.status_code, 200)

    # ── Data Quality ──────────────────────────────────────────────────────────

    def test_quality_loads(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}/quality')
        self.assertEqual(resp.status_code, 200)

    # ── Data Story ────────────────────────────────────────────────────────────

    def test_story_loads(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}/story')
        self.assertEqual(resp.status_code, 200)

    # ── NLQ ───────────────────────────────────────────────────────────────────

    def test_nlq_get(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}/nlq')
        self.assertEqual(resp.status_code, 200)

    def test_nlq_top_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'show top 3 by sales'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Top', resp.data)

    def test_nlq_average_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'what is the average sales'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Average', resp.data)

    def test_nlq_distribution_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'show distribution of sales'})
        self.assertEqual(resp.status_code, 200)

    def test_nlq_correlation_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'show correlation between columns'})
        self.assertEqual(resp.status_code, 200)

    def test_nlq_count_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'how many city'})
        self.assertEqual(resp.status_code, 200)

    def test_nlq_outlier_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'show outliers in sales'})
        self.assertEqual(resp.status_code, 200)

    def test_nlq_missing_query(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'how many missing values'})
        self.assertEqual(resp.status_code, 200)

    def test_nlq_unmatched_query_returns_page(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/nlq',
                                data={'query': 'xyzzy unknown intent'})
        self.assertEqual(resp.status_code, 200)

    # ── Chart Builder ─────────────────────────────────────────────────────────

    def test_create_bar_chart(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/chart', data={
            'chart_type': 'bar', 'x_col': 'city', 'y_col': 'sales', 'title': 'Sales by City',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(Report.query.filter_by(user_id=self.user.id).first())

    def test_create_pie_chart(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/chart', data={
            'chart_type': 'pie', 'x_col': 'city', 'y_col': 'sales', 'title': 'Pie',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    def test_create_heatmap(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/chart', data={
            'chart_type': 'heatmap', 'x_col': 'sales', 'title': 'Heatmap',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    # ── Download ──────────────────────────────────────────────────────────────

    def test_download_dataset(self):
        resp = self.client.get(f'/dataset/{self.dataset.id}/download')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'city', resp.data)

    # ── Reports ───────────────────────────────────────────────────────────────

    def test_reports_page(self):
        resp = self.client.get('/reports')
        self.assertEqual(resp.status_code, 200)

    def test_delete_report(self):
        cfg = json.dumps({'x': 'city', 'y': 'sales', 'color': None, 'chart_json': '{}'})
        report = Report(title='Test', chart_type='bar', config=cfg,
                        dataset_id=self.dataset.id, user_id=self.user.id)
        db.session.add(report)
        db.session.commit()
        resp = self.client.post(f'/report/{report.id}/delete', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Report.query.get(report.id))

    # ── API endpoints ─────────────────────────────────────────────────────────

    def test_api_live_stats(self):
        resp = self.client.get('/api/live-stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('datasets', data)
        self.assertIn('reports', data)
        self.assertIn('total_rows', data)

    def test_api_dataset_stats(self):
        resp = self.client.get(f'/api/dataset/{self.dataset.id}/stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('stats', data)
        self.assertIn('sales', data['stats'])

    def test_api_stats_404(self):
        resp = self.client.get('/api/dataset/9999/stats')
        self.assertEqual(resp.status_code, 404)

    # ── Toggle visibility ─────────────────────────────────────────────────────

    def test_toggle_visibility(self):
        original = self.dataset.is_public
        self.client.post(f'/dataset/{self.dataset.id}/toggle-visibility')
        db.session.refresh(self.dataset)
        self.assertNotEqual(self.dataset.is_public, original)

    # ── Data cleaning ─────────────────────────────────────────────────────────

    def test_clean_drop_duplicates(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/clean',
                                data={'action': 'drop_duplicates'},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    def test_clean_fill_mean(self):
        resp = self.client.post(f'/dataset/{self.dataset.id}/clean',
                                data={'action': 'fill_mean', 'col': 'sales'},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
