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


# ── 2FA : le compteur d'essais vit en base, pas dans le cookie ──────────────

def _admin_avec_2fa(app, max_essais=3):
    import pyotp
    app.config['LOGIN_MAX_ATTEMPTS'] = max_essais
    app.config['REQUIRE_2FA_ADMIN'] = False
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('bon-mdp')
    admin.totp_secret = pyotp.random_base32()
    db.session.commit()
    return admin


def _code_faux(admin):
    import pyotp
    bon = pyotp.TOTP(admin.totp_secret).now()
    return '000000' if bon != '000000' else '111111'


def test_2fa_rejouer_le_cookie_ne_remet_pas_le_compteur_a_zero(app):
    """Le compteur était dans le cookie de session : rejouer le cookie pris
    avant les échecs redonnait tous les essais."""
    import pyotp
    admin = _admin_avec_2fa(app)
    client = app.test_client()
    r = _login(client, 'admin', 'bon-mdp', '10.0.0.1')
    assert '/2fa' in r.headers['Location']
    cookie_avant = client.get_cookie('session').value

    for _ in range(3):
        client.post('/2fa', data={'code': _code_faux(admin)})
    db.session.refresh(admin)
    assert admin.totp_locked_until is not None

    # Rejeu du cookie « 0 essai » avec le BON code : toujours refusé.
    rejeu = app.test_client()
    rejeu.set_cookie('session', cookie_avant)
    r = rejeu.post('/2fa', data={'code': pyotp.TOTP(admin.totp_secret).now()})
    assert '/login' in r.headers['Location']
    assert rejeu.get('/inventory/').status_code == 302


def test_2fa_se_reconnecter_ne_redonne_pas_d_essais(app):
    """Avec le mot de passe, se reconnecter suffisait à repartir de zéro."""
    import pyotp
    admin = _admin_avec_2fa(app)
    client = app.test_client()
    for _ in range(3):
        _login(client, 'admin', 'bon-mdp', '10.0.0.1')
        client.post('/2fa', data={'code': _code_faux(admin)})
    _login(client, 'admin', 'bon-mdp', '10.0.0.1')
    r = client.post('/2fa', data={'code': pyotp.TOTP(admin.totp_secret).now()})
    assert '/login' in r.headers['Location']


def test_2fa_bon_code_remet_le_compteur_a_zero(app):
    import pyotp
    admin = _admin_avec_2fa(app)
    client = app.test_client()
    _login(client, 'admin', 'bon-mdp', '10.0.0.1')
    client.post('/2fa', data={'code': _code_faux(admin)})
    r = client.post('/2fa', data={'code': pyotp.TOTP(admin.totp_secret).now()})
    assert '/login' not in r.headers['Location']
    db.session.refresh(admin)
    assert admin.totp_failed_count == 0
    assert client.get('/inventory/').status_code == 200


# ── X-Forwarded-For : seule l'entrée ajoutée par le proxy compte ────────────

def test_falsifier_x_forwarded_for_ne_contourne_pas_le_blocage(app):
    """Le client écrit ce qu'il veut en tête de X-Forwarded-For ; le reverse
    proxy ajoute l'adresse réelle à la fin. Seule cette dernière compte."""
    app.config['LOGIN_MAX_ATTEMPTS'] = 3
    client = app.test_client()
    for i in range(5):
        client.post('/login', data={'username': 'admin', 'password': 'mauvais'},
                    headers={'X-Forwarded-For': f'1.2.3.{i}, 10.0.0.66'})
    th = LoginThrottle.query.filter_by(username='admin', ip='10.0.0.66').first()
    assert th is not None and th.locked_until is not None
    assert LoginThrottle.query.filter(LoginThrottle.ip.like('1.2.3.%')).count() == 0


# ── LDAP : un compte AD homonyme n'ouvre pas un compte local ────────────────

def _ad_accepte(monkeypatch, identifiants):
    import app.ldap_auth as ldap_auth
    monkeypatch.setattr(ldap_auth, 'ldap_authenticate',
                        lambda u, p: {} if (u, p) in identifiants else None)


def test_compte_ad_homonyme_n_ouvre_pas_le_compte_local(app, monkeypatch):
    _ad_accepte(monkeypatch, {('admin', 'mdp-ad')})
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('mdp-local')
    db.session.commit()

    client = app.test_client()
    r = _login(client, 'admin', 'mdp-ad', '10.0.0.1')
    assert r.status_code == 200 and b'Identifiants incorrects' in r.data
    assert client.get('/inventory/').status_code == 302
    # Le mot de passe local, lui, fonctionne toujours.
    r = _login(client, 'admin', 'mdp-local', '10.0.0.1')
    assert r.status_code == 302


def test_compte_ad_ouvre_toujours_son_propre_compte(app, monkeypatch):
    _ad_accepte(monkeypatch, {('jdupont', 'mdp-ad')})
    client = app.test_client()
    assert _login(client, 'jdupont', 'mdp-ad', '10.0.0.1').status_code == 302
    u = User.query.filter_by(username='jdupont').first()
    assert u is not None and u.is_ldap and u.role != 'admin'
    # Seconde connexion : le compte provisionné par l'AD est retrouvé.
    client2 = app.test_client()
    assert _login(client2, 'jdupont', 'mdp-ad', '10.0.0.1').status_code == 302
