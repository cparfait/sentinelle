"""Sécurité du login : anti-bruteforce par (identifiant, IP) et 2FA admin."""
from app import db
from app.models import User, LoginThrottle


def _login(client, username, password, ip):
    return client.post('/login', data={'username': username, 'password': password},
                       headers={'X-Forwarded-For': ip})


def test_blocage_par_ip_n_affecte_pas_les_autres_ip(app):
    """Un attaquant ne doit pas pouvoir verrouiller un compte depuis une IP A
    et bloquer ainsi l'utilisateur légitime qui se connecte depuis une IP B."""
    app.config['LOGIN_MAX_ATTEMPTS'] = 2
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('bon-mdp')
    db.session.commit()

    client = app.test_client()
    # IP de l'attaquant : on dépasse le seuil -> blocage de (admin, IP_A)
    for _ in range(2):
        _login(client, 'admin', 'mauvais', '10.0.0.66')
    th = LoginThrottle.query.filter_by(username='admin', ip='10.0.0.66').first()
    assert th is not None and th.locked_until is not None

    # IP A bloquée
    r = _login(client, 'admin', 'bon-mdp', '10.0.0.66')
    assert b'Trop de tentatives' in r.data
    # IP B (utilisateur légitime) : connexion possible
    r = _login(app.test_client(), 'admin', 'bon-mdp', '192.168.1.10')
    assert r.status_code in (301, 302)  # redirige vers le tableau de bord


def test_2fa_admin_obligatoire_redirige_vers_le_profil(app):
    app.config['REQUIRE_2FA_ADMIN'] = True
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('bon-mdp')
    admin.totp_secret = None  # admin sans 2FA
    db.session.commit()

    client = app.test_client()
    _login(client, 'admin', 'bon-mdp', '127.0.0.1')
    # toute page hors profil/logout est renvoyée vers le profil
    r = client.get('/inventory/')
    assert r.status_code == 302
    assert '/profile' in r.headers['Location']
    # le profil reste accessible (pour activer la 2FA)
    assert client.get('/profile').status_code == 200


def test_2fa_admin_non_impose_si_option_off(app):
    app.config['REQUIRE_2FA_ADMIN'] = False
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('bon-mdp')
    db.session.commit()
    client = app.test_client()
    _login(client, 'admin', 'bon-mdp', '127.0.0.1')
    assert client.get('/inventory/').status_code == 200
