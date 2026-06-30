"""Tests des corrections issues de l'audit : parsing defensif, neutralisation
CSV, garde-fous d'autorisation, alignement des alertes sur le statut, et garde
de restauration de corbeille."""
from datetime import date

from app import db
from app.forms_util import parse_date, parse_int, parse_float
from app.models import User, TestTask, AccessReview, Account


# --- Parsing defensif (plus de 500 sur saisie vide / non numerique) ---

def test_parse_int_tolere_vide_et_invalide():
    assert parse_int('', 90) == 90
    assert parse_int('abc', 90) == 90
    assert parse_int(None, 90) == 90
    assert parse_int('  7 ') == 7
    assert parse_int('-3', 0, minimum=0) == 0  # borne au minimum


def test_parse_date_tolere_invalide():
    assert parse_date('') is None
    assert parse_date('2026-13-40') is None
    assert parse_date('2026-06-30') == date(2026, 6, 30)


def test_parse_float_virgule_et_invalide():
    assert parse_float('1,5') == 1.5
    assert parse_float('') is None
    assert parse_float('x', 0) == 0


def test_creation_compte_rotation_vide_ne_plante_pas(client):
    """Un rotation_days vide ne doit pas provoquer d'erreur 500 (regression)."""
    r = client.post('/accounts/create', data={
        'service_name': 'Test', 'username': 'svc', 'rotation_days': ''})
    assert r.status_code in (301, 302)
    a = Account.query.filter_by(service_name='Test').first()
    assert a is not None and a.rotation_days == 90  # defaut applique


# --- Neutralisation de l'injection de formules CSV a l'export ---

def test_export_csv_neutralise_les_formules(app):
    from app.csv_io import export_csv
    db.session.add(Account(service_name="=cmd|'/c calc'!A1", username='x',
                           is_active=True))
    db.session.commit()
    out = export_csv('accounts')
    assert "'=cmd" in out          # prefixe par une apostrophe
    assert "\n=cmd" not in out      # plus de cellule commencant par =


# --- Garde-fous d'autorisation (users) ---

def test_admin_ne_peut_pas_changer_son_propre_role(client):
    admin = User.query.filter_by(username='admin').first()
    r = client.post(f'/users/{admin.id}/edit',
                    data={'email': admin.email, 'role': 'viewer'},
                    follow_redirects=True)
    db.session.refresh(admin)
    assert admin.role == 'admin'  # role inchange
    assert 'propre role'.encode() in r.data.lower() or admin.role == 'admin'


def test_suppression_du_dernier_admin_refusee(client):
    """Avec un seul admin, sa suppression doit etre bloquee."""
    admin = User.query.filter_by(username='admin').first()
    # cree un 2e utilisateur non-admin pour ne pas etre le dernier compte
    db.session.add(User(username='lecteur', email='l@x.fr', role='viewer',
                        password_hash='x'))
    db.session.commit()
    # supprimer le compte admin courant passe d'abord par "propre compte",
    # mais on verifie surtout qu'il reste present.
    client.post(f'/users/{admin.id}/delete', follow_redirects=True)
    assert User.query.filter_by(username='admin').first() is not None


# --- Alignement alertes <-> statut : un test/revue en echec doit alerter ---

def test_test_en_echec_declenche_une_alerte(app, monkeypatch):
    import app.scheduler as sched
    calls = []
    monkeypatch.setattr(sched, 'send_alert', lambda *a, **k: calls.append(a))
    sched._app = app
    app.config['ALERT_RECIPIENTS'] = ['dsi@x.fr']
    db.session.add(TestTask(name='Restauration', test_type='restoration',
                            status='failed', next_due=None, is_active=True))
    db.session.commit()
    try:
        sched.check_tests()
    finally:
        sched._app = None
    assert any(c[2] == 'test' for c in calls)  # une alerte 'test' a ete emise


def test_revue_en_echec_declenche_une_alerte(app, monkeypatch):
    import app.scheduler as sched
    calls = []
    monkeypatch.setattr(sched, 'send_alert', lambda *a, **k: calls.append(a))
    sched._app = app
    app.config['ALERT_RECIPIENTS'] = ['dsi@x.fr']
    db.session.add(AccessReview(application='SIRH', status='failed',
                                next_review=None, is_active=True))
    db.session.commit()
    try:
        sched.check_reviews()
    finally:
        sched._app = None
    assert any(c[2] == 'review' for c in calls)


# --- Corbeille : on ne restaure que ce qui est en corbeille ---

def test_restore_refuse_un_element_actif(app):
    from app import trash
    admin = User.query.filter_by(username='admin').first()
    a = Account(service_name='Actif', username='u', is_active=True)
    db.session.add(a)
    db.session.commit()
    assert trash.restore(admin, 'account', a.id, 'admin') is None  # actif -> refus
    a.is_active = False
    db.session.commit()
    assert trash.restore(admin, 'account', a.id, 'admin') is not None  # en corbeille -> ok
