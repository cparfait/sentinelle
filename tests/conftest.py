"""Fixtures pytest : application en base SQLite memoire, sans scheduler."""
import pytest

from app import create_app, db
from config import Config


class _TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'   # base memoire, jetee apres chaque test


@pytest.fixture()
def app():
    application = create_app(_TestConfig)
    with application.app_context():
        yield application
        db.session.remove()


@pytest.fixture()
def client(app):
    """Client HTTP connecte en admin."""
    from app.models import User
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('mdp-de-test')
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'mdp-de-test'})
    return c
