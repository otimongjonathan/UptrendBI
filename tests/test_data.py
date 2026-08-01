import io
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app, db
from app.models import Dataset, User

SAMPLE_DF = pd.DataFrame({'name': ['Alice', 'Bob'], 'score': [95, 87]})


class DataRouteTestCase(unittest.TestCase):
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

        self.client = self.app.test_client()
        self.client.post('/login', data={'email': 'tester@example.com', 'password': 'secret123'})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tmpdir.cleanup()

    # ── CSV Upload ────────────────────────────────────────────────────────────

    def test_upload_valid_csv(self):
        csv_bytes = SAMPLE_DF.to_csv(index=False).encode()
        resp = self.client.post('/data/upload', data={
            'name': 'Test Dataset',
            'file': (io.BytesIO(csv_bytes), 'test.csv'),
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        ds = Dataset.query.filter_by(name='Test Dataset').first()
        self.assertIsNotNone(ds)
        self.assertEqual(ds.rows, 2)
        self.assertEqual(ds.columns, 2)

    def test_upload_invalid_extension_rejected(self):
        resp = self.client.post('/data/upload', data={
            'name': 'Bad File',
            'file': (io.BytesIO(b'not,a,csv'), 'data.txt'),
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Dataset.query.filter_by(name='Bad File').first())

    def test_upload_no_file_rejected(self):
        resp = self.client.post('/data/upload', data={'name': 'Empty'},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Dataset.query.filter_by(name='Empty').first())

    def test_upload_public_visibility(self):
        csv_bytes = SAMPLE_DF.to_csv(index=False).encode()
        self.client.post('/data/upload', data={
            'name': 'Public DS',
            'visibility': 'public',
            'file': (io.BytesIO(csv_bytes), 'pub.csv'),
        }, content_type='multipart/form-data', follow_redirects=True)
        ds = Dataset.query.filter_by(name='Public DS').first()
        self.assertTrue(ds.is_public)

    # ── Dataset Deletion ──────────────────────────────────────────────────────

    def test_delete_dataset_removes_record_and_file(self):
        csv_path = os.path.join(self.tmpdir.name, 'del.csv')
        SAMPLE_DF.to_csv(csv_path, index=False)
        ds = Dataset(name='ToDelete', filename='del.csv',
                     rows=2, columns=2, user_id=self.user.id)
        db.session.add(ds)
        db.session.commit()
        ds_id = ds.id

        resp = self.client.post(f'/data/delete/{ds_id}', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Dataset.query.get(ds_id))
        self.assertFalse(os.path.exists(csv_path))

    # ── DB Export ─────────────────────────────────────────────────────────────

    def test_export_from_db_saves_dataset(self):
        with patch('app.routes.data._db_load_df', return_value=SAMPLE_DF):
            resp = self.client.post('/data/export-from-db', data={
                'name': 'DB Export', 'visibility': 'private', 'query': 'SELECT 1',
            }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        ds = Dataset.query.filter_by(name='DB Export').first()
        self.assertIsNotNone(ds)
        self.assertEqual(ds.rows, 2)
        self.assertFalse(ds.is_public)

    def test_export_from_db_empty_result_warns(self):
        with patch('app.routes.data._db_load_df', return_value=pd.DataFrame()):
            resp = self.client.post('/data/export-from-db', data={
                'name': 'Empty Export', 'query': 'SELECT 1',
            }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Dataset.query.filter_by(name='Empty Export').first())

    def test_export_from_db_connection_error(self):
        with patch('app.routes.data._db_load_df', side_effect=Exception('conn refused')):
            resp = self.client.post('/data/export-from-db', data={
                'name': 'Fail Export', 'query': 'SELECT 1',
            }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(Dataset.query.filter_by(name='Fail Export').first())


if __name__ == '__main__':
    unittest.main()
