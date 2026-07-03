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


def test_page_connecteurs_contient_webhooks(app, client):
    body = client.get('/connecteurs/').data.decode('utf-8')
    assert 'Notifications (webhooks)' in body
    assert 'teams_webhook' in body and 'wh_url' in body


def test_enregistrement_webhooks_globaux(app, client):
    r = client.post('/connecteurs/webhooks', data={
        'action': 'save_webhooks',
        'teams_webhook': 'https://teams.example/hook',
        'slack_webhook': '', 'discord_webhook': ''}, follow_redirects=True)
    assert r.status_code == 200
    assert app.config['TEAMS_WEBHOOK_URL'] == 'https://teams.example/hook'


def test_ajout_et_suppression_webhook_categorie(app, client):
    from app import db
    from app.models import Webhook
    r = client.post('/connecteurs/webhooks', data={
        'action': 'add_webhook', 'wh_category': 'all', 'wh_channel': 'slack',
        'wh_url': 'https://hooks.slack.com/services/xxx', 'wh_label': 'Général'},
        follow_redirects=True)
    assert r.status_code == 200
    w = Webhook.query.filter_by(channel='slack').first()
    assert w is not None and w.category == 'all'
    # URL non https refusée
    client.post('/connecteurs/webhooks', data={
        'action': 'add_webhook', 'wh_category': 'all', 'wh_channel': 'teams',
        'wh_url': 'http://interne/hook'}, follow_redirects=True)
    assert Webhook.query.filter_by(channel='teams').first() is None
    # Suppression
    client.post('/connecteurs/webhooks', data={'action': 'delete_webhook', 'wh_id': w.id},
                follow_redirects=True)
    assert db.session.get(Webhook, w.id) is None


def test_preferences_ne_contient_plus_les_webhooks(app, client):
    body = client.get('/preferences').data.decode('utf-8')
    assert 'teams_webhook' not in body and 'wh_url' not in body


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
