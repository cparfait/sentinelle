"""Test de demarrage minimal pour la CI : l'app se cree et repond.

Ne demarre pas le planificateur (TESTING) et n'envoie aucun mail.
"""
import sys
from app import create_app
from config import Config


class CIConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///ci_test.db'


def main():
    app = create_app(CIConfig)
    client = app.test_client()

    # La page de login doit repondre
    r = client.get('/login')
    assert r.status_code == 200, f'/login -> {r.status_code}'

    # Une page protegee doit rediriger vers le login
    r = client.get('/')
    assert r.status_code in (301, 302), f'/ (non connecte) -> {r.status_code}'

    print('Smoke test OK : application demarre et repond.')


if __name__ == '__main__':
    try:
        main()
    except AssertionError as e:
        print('Smoke test ECHEC :', e)
        sys.exit(1)
