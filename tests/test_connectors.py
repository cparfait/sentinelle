"""Espace « Connecteurs » : page dédiée + activation/clé du connecteur Sesame
(déplacés depuis la page Préférences)."""
from app.models import User


def test_page_connecteurs_admin(app, client):
    r = client.get('/connecteurs/')
    assert r.status_code == 200
    body = r.data.decode('utf-8')
    assert 'Connecteurs' in body and 'Sesame' in body


def test_activation_connecteur_sesame(app, client):
    app.config['SESAME_API_ENABLED'] = False
    r = client.post('/connecteurs/sesame',
                    data={'action': 'save', 'sesame_enabled': 'on'},
                    follow_redirects=True)
    assert r.status_code == 200
    assert app.config['SESAME_API_ENABLED'] is True
    # Désactivation
    r = client.post('/connecteurs/sesame', data={'action': 'save'},
                    follow_redirects=True)
    assert app.config['SESAME_API_ENABLED'] is False


def test_generation_cle_sesame(app, client):
    r = client.post('/connecteurs/sesame', data={'action': 'generate_key'},
                    follow_redirects=True)
    assert r.status_code == 200
    token = app.config.get('SESAME_API_TOKEN')
    assert token and len(token) >= 20
    # La clé en clair est affichée une seule fois (juste après génération).
    assert token in r.data.decode('utf-8')


def test_connecteurs_reserve_admin(app):
    """Un non-admin ne doit pas accéder à l'espace Connecteurs."""
    from app import db
    u = User(username='lecteur', email='l@ex.fr', role='viewer')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'lecteur', 'password': 'x'})
    r = c.get('/connecteurs/', follow_redirects=False)
    assert r.status_code in (301, 302)  # redirigé (accès refusé)
