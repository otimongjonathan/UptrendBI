import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app, db
from app.models import Dataset, User


class ExportDatasetTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(TESTING=True, UPLOAD_FOLDER=self.tmpdir.name)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

        self.user = User(username='tester', email='tester@example.com')
        self.user.set_password('secret123')
        db.session.add(self.user)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        self.tmpdir.cleanup()

    def test_export_db_query_as_dataset(self):
        df = pd.DataFrame({'city': ['Nairobi', 'Kampala'], 'sales': [120, 80]})

        with patch('app.routes.data._db_load_df', return_value=df):
            response = self.client.post('/login', data={'email': 'tester@example.com', 'password': 'secret123'})
            self.assertEqual(response.status_code, 302)

            response = self.client.post('/data/export-from-db', data={
                'name': 'Sales export',
                'visibility': 'public',
                'query': 'SELECT 1',
            }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        dataset = Dataset.query.filter_by(name='Sales export').first()
        self.assertIsNotNone(dataset)
        self.assertEqual(dataset.rows, 2)
        self.assertEqual(dataset.columns, 2)
        self.assertTrue(dataset.is_public)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir.name, dataset.filename)))


if __name__ == '__main__':
    unittest.main()
