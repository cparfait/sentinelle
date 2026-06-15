"""Routes transverses : sonde de supervision et export ICS de l'agenda."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import Certificate, SchedulerRun


def test_healthz_sans_authentification(app):
    r = app.test_client().get('/healthz')
    assert r.status_code == 200
    data = r.get_json()
    assert data['status'] == 'ok'
    assert data['scheduler'] == 'no_run_yet'  # aucun job encore execute


def test_healthz_scheduler_en_panne(app):
    db.session.add(SchedulerRun(job_id='check_passwords', status='ok',
                                run_at=datetime.now(timezone.utc) - timedelta(hours=30)))
    db.session.commit()
    r = app.test_client().get('/healthz')
    assert r.status_code == 503
    assert r.get_json()['scheduler'] == 'stale'


def test_healthz_scheduler_recent(app):
    db.session.add(SchedulerRun(job_id='check_passwords', status='ok',
                                run_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    db.session.commit()
    r = app.test_client().get('/healthz')
    assert r.status_code == 200


def test_agenda_ics(app, client):
    db.session.add(Certificate(service_name='Portail RH', domain='rh.exemple.fr',
                               expiry_date=datetime.now(timezone.utc).date() + timedelta(days=12)))
    db.session.commit()
    r = client.get('/agenda.ics')
    assert r.status_code == 200
    assert r.mimetype == 'text/calendar'
    body = r.data.decode('utf-8')
    assert 'BEGIN:VCALENDAR' in body and 'END:VCALENDAR' in body
    assert 'Portail RH' in body
    assert 'DTSTART;VALUE=DATE:' in body


def test_agenda_ics_exige_connexion(app):
    r = app.test_client().get('/agenda.ics')
    assert r.status_code in (301, 302)  # redirection vers /login


def test_ics_abonnement_par_jeton(app, client):
    """Le jeton personnel permet l'abonnement calendrier sans session."""
    from app.models import User
    # generation du jeton depuis la page Agenda
    r = client.post('/agenda/ics-token')
    assert r.status_code in (301, 302)
    admin = User.query.filter_by(username='admin').first()
    assert admin.ics_token

    anonyme = app.test_client()
    r = anonyme.get(f'/agenda.ics?token={admin.ics_token}')
    assert r.status_code == 200
    assert r.mimetype == 'text/calendar'
    assert 'Content-Disposition' not in r.headers  # flux, pas de telechargement force

    r = anonyme.get('/agenda.ics?token=jeton-invalide')
    assert r.status_code == 403

    # desactivation : l'ancien lien cesse de fonctionner
    ancien = admin.ics_token
    client.post('/agenda/ics-token', data={'action': 'disable'})
    assert User.query.filter_by(username='admin').first().ics_token is None
    assert anonyme.get(f'/agenda.ics?token={ancien}').status_code == 403


def test_corbeille_equipement_restaurer_et_purger(app):
    """Un equipement supprime apparait en corbeille, se restaure, et sa purge
    detache les elements lies (vue 360°)."""
    from app.models import Equipment, User
    from app.trash import list_trashed, restore, purge_one
    admin = User.query.filter_by(username='admin').first()

    e = Equipment(name='SRV-OBSOLETE', is_active=False)
    db.session.add(e)
    db.session.commit()
    eid = e.id

    groupes = {g['etype']: g for g in list_trashed(admin)}
    assert 'equipment' in groupes
    assert groupes['equipment']['items'][0]['name'] == 'SRV-OBSOLETE'

    # restauration (pas de modele d'historique : ne doit pas planter)
    assert restore(admin, 'equipment', str(eid), 'admin') == ('Inventaire', 'SRV-OBSOLETE')
    assert db.session.get(Equipment, eid).is_active is True

    # purge : l'equipment_id du certificat lie est remis a NULL
    e2 = Equipment(name='SRV-A-PURGER', is_active=False)
    db.session.add(e2)
    db.session.commit()
    cert = Certificate(service_name='svc', domain='d.fr',
                       expiry_date=datetime.now(timezone.utc).date(),
                       equipment_id=e2.id)
    db.session.add(cert)
    db.session.commit()
    assert purge_one(admin, 'equipment', str(e2.id)) == ('Inventaire', 'SRV-A-PURGER')
    assert cert.equipment_id is None
    assert db.session.get(Equipment, e2.id) is None


def test_fiche_equipement_vue_360(app, client):
    """La fiche d'un equipement liste les elements lies (vue 360°)."""
    from app.models import Equipment, Backup
    e = Equipment(name='SRV-PROD-01', kind='vm', criticality=3)
    db.session.add(e)
    db.session.commit()
    db.session.add(Certificate(service_name='Intranet', domain='intra.exemple.fr',
                               expiry_date=datetime.now(timezone.utc).date() + timedelta(days=90),
                               equipment_id=e.id))
    db.session.add(Backup(service_name='Veeam SRV-PROD-01', frequency='daily',
                          equipment_id=e.id))
    db.session.commit()
    r = client.get(f'/inventory/{e.id}')
    assert r.status_code == 200
    body = r.data.decode('utf-8')
    assert 'Éléments liés' in body
    assert 'intra.exemple.fr' in body
    assert 'Veeam SRV-PROD-01' in body
