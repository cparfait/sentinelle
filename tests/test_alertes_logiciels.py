"""Alertes logiciels : fin de vie sans successeur et plafond de licences
dépassé, chaque lundi, débrayables depuis Préférences et routées vers la
catégorie « Logiciels »."""
from datetime import date
from unittest.mock import patch

from app import db
from app.models import Software, Role, User

LUNDI = date(2026, 9, 21)
MARDI = date(2026, 9, 22)


def _lancer(app, today):
    import app.scheduler as sched
    sched._app = app
    try:
        with patch('app.scheduler.send_alert') as mock_send:
            sched.check_software(today=today)
            return mock_send
    finally:
        sched._app = None


def test_fin_de_vie_alerte_le_lundi(app):
    db.session.add(Software(name='Ciril', lifecycle='fin_de_vie'))
    db.session.commit()
    m = _lancer(app, LUNDI)
    assert m.call_count == 1
    subject, body, entity_type, _id, name = m.call_args[0]
    assert 'Ciril' in subject and 'fin de vie' in body
    assert entity_type == 'software' and name == 'Ciril'
    assert m.call_args[1]['status'] == 'warning'


def test_pas_d_alerte_les_autres_jours(app):
    db.session.add(Software(name='Ciril', lifecycle='fin_de_vie'))
    db.session.commit()
    assert not _lancer(app, MARDI).called


def test_plafond_de_licences_depasse(app):
    db.session.add(Software(name='Paie', users_count=60, users_max=50))
    db.session.commit()
    m = _lancer(app, LUNDI)
    assert m.call_count == 1
    assert 'Plafond de licences dépassé' in m.call_args[0][1]


def test_un_logiciel_sain_ou_abandonne_n_alerte_pas(app):
    db.session.add_all([
        Software(name='OK', lifecycle='production', users_count=10, users_max=50),
        Software(name='Sans plafond', users_count=999),   # users_max NULL = illimité
        # Un logiciel abandonné n'est plus en service : rien à surveiller.
        Software(name='Abandonné', lifecycle='abandonne'),
        Software(name='Corbeille', lifecycle='fin_de_vie', is_active=False),
    ])
    db.session.commit()
    assert not _lancer(app, LUNDI).called


def test_l_interrupteur_coupe_les_alertes(app):
    db.session.add(Software(name='Ciril', lifecycle='fin_de_vie'))
    db.session.commit()
    app.config['SOFTWARE_ALERTS'] = False
    assert not _lancer(app, LUNDI).called


def test_le_report_est_respecte(app):
    from app.snooze import set_snooze
    sw = Software(name='Ciril', lifecycle='fin_de_vie')
    db.session.add(sw)
    db.session.commit()
    set_snooze('software', sw.id, 30)
    assert not _lancer(app, LUNDI).called


# ── Préférences ──

def test_l_interrupteur_se_regle_depuis_les_preferences(client, app):
    html = client.get('/preferences').get_data(as_text=True)
    assert 'name="software_alerts"' in html
    assert 'Alertes logiciels activées' in html
    client.post('/preferences', data={'action': 'save_software_alerts'},
                follow_redirects=True)
    assert app.config['SOFTWARE_ALERTS'] is False
    # Persisté en base : survit à un rechargement de la configuration.
    from app import config_store
    config_store.load(app)
    assert app.config['SOFTWARE_ALERTS'] is False
    client.post('/preferences', data={'action': 'save_software_alerts',
                                      'software_alerts': 'on'}, follow_redirects=True)
    assert app.config['SOFTWARE_ALERTS'] is True


def test_les_logiciels_ont_leur_liste_de_destinataires(client, app):
    from app.config_store import ALERT_CATEGORIES, ALERT_CATEGORY_LABELS
    from app.alerts import alert_recipients_for
    assert 'software' in ALERT_CATEGORIES and ALERT_CATEGORY_LABELS['software'] == 'Logiciels'
    html = client.get('/preferences').get_data(as_text=True)
    assert 'name="alert_recipients_software"' in html
    app.config['ALERT_RECIPIENTS'] = ['dsi@mairie.fr']
    app.config['ALERT_RECIPIENTS_SOFTWARE'] = ['applis@mairie.fr']
    assert alert_recipients_for('software') == ['applis@mairie.fr']


# ── Report depuis la fiche, avec le droit de l'inventaire ──

def _client_pour(app, permissions):
    role = Role(name='gestionnaire', permissions=permissions)
    db.session.add(role)
    db.session.commit()
    u = User(username='gest', email='g@x.fr', role='gestionnaire')
    u.set_password('Gest-2026!')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'gest', 'password': 'Gest-2026!'})
    return c


def test_la_categorie_de_droits_d_une_alerte(app):
    from app.snooze import permission_category
    assert permission_category('software') == 'inventory'
    assert permission_category('equipment') == 'inventory'
    assert permission_category('account') == 'accounts'


def test_le_report_d_une_alerte_logiciel_demande_le_droit_inventaire(app):
    from app.snooze import is_snoozed
    sw = Software(name='Ciril', lifecycle='fin_de_vie')
    db.session.add(sw)
    db.session.commit()
    c = _client_pour(app, {'inventory': 2})
    html = c.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Reporter…' in html
    r = c.post('/alerts/snooze', data={'entity_type': 'software', 'entity_id': str(sw.id),
                                       'days': '7'})
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/inventory/logiciels/{sw.id}')
    assert is_snoozed('software', sw.id)


def test_sans_droit_d_ecriture_pas_de_report(app):
    from app.snooze import is_snoozed
    sw = Software(name='Ciril')
    db.session.add(sw)
    db.session.commit()
    c = _client_pour(app, {'inventory': 1})
    assert 'Reporter…' not in c.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    c.post('/alerts/snooze', data={'entity_type': 'software', 'entity_id': str(sw.id), 'days': '7'})
    assert not is_snoozed('software', sw.id)
