import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app, db
from app.models import User


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _register(self, username='alice', email='alice@example.com', password='pass1234'):
        return self.client.post('/register', data={
            'username': username, 'email': email, 'password': password,
        }, follow_redirects=True)

    def _login(self, email='alice@example.com', password='pass1234'):
        return self.client.post('/login', data={
            'email': email, 'password': password,
        }, follow_redirects=True)

    # ── Registration ──────────────────────────────────────────────────────────

    def test_register_creates_user(self):
        self._register()
        self.assertIsNotNone(User.query.filter_by(email='alice@example.com').first())

    def test_register_duplicate_email_rejected(self):
        self._register()
        resp = self._register(username='bob')
        self.assertIn(b'already registered', resp.data)

    def test_register_duplicate_username_rejected(self):
        self._register()
        resp = self._register(email='other@example.com')
        self.assertIn(b'already taken', resp.data)

    # ── Login / Logout ────────────────────────────────────────────────────────

    def test_login_valid_credentials(self):
        self._register()
        resp = self._login()
        self.assertEqual(resp.status_code, 200)

    def test_login_wrong_password(self):
        self._register()
        resp = self._login(password='wrongpass')
        self.assertIn(b'Invalid', resp.data)

    def test_login_unknown_email(self):
        resp = self._login(email='nobody@example.com')
        self.assertIn(b'Invalid', resp.data)

    def test_logout_redirects_to_login(self):
        self._register()
        self._login()
        resp = self.client.get('/logout', follow_redirects=True)
        self.assertIn(b'login', resp.data.lower())

    # ── Protected routes redirect unauthenticated users ───────────────────────

    def test_dashboard_requires_login(self):
        resp = self.client.get('/', follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))


if __name__ == '__main__':
    unittest.main()
