"""Routes transverses : sonde de supervision et export ICS de l'agenda."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import Certificate, SchedulerRun, Equipment, Contract


def test_dashboard_se_charge_pour_un_admin(app, client):
    """Charge la page d'accueil connecté : garde-fou contre une régression
    d'import (ex. Contract utilisé mais non importé -> NameError silencieux)."""
    r = client.get('/')
    assert r.status_code == 200


def test_agenda_inclut_garanties_et_contrats(app, client):
    e = Equipment(name='SRV-GARANTIE',
                  warranty_end=datetime.now(timezone.utc).date() + timedelta(days=20))
    db.session.add(e)
    db.session.add(Contract(name='Maintenance baie', kind='maintenance',
                            end_date=datetime.now(timezone.utc).date() + timedelta(days=30)))
    db.session.commit()
    body = client.get('/agenda').data.decode('utf-8')
    assert 'SRV-GARANTIE' in body and 'garantie' in body.lower()
    assert 'Maintenance baie' in body
    # et dans le flux ICS
    ics = client.get('/agenda.ics').data.decode('utf-8')
    assert 'SRV-GARANTIE' in ics and 'Maintenance baie' in ics


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


def test_fiche_equipement_sections_par_type(client):
    """La fiche affiche les sections propres a chaque nature (champs vides
    compris) et les infos de continuite sous la fiche.

    On cherche des LIBELLES DE CHAMP et non des titres de section : « Réseau »
    est aussi un onglet de navigation, et l'assertion passerait pour de
    mauvaises raisons."""
    from app.models import Equipment
    vm = Equipment(name='VM-T', kind='vm')
    ph = Equipment(name='PHY-T', kind='physical')
    nas = Equipment(name='NAS-T', kind='nas')
    baie = Equipment(name='BAIE-T', kind='storage')
    sw = Equipment(name='SW-T', kind='network')
    db.session.add_all([vm, ph, nas, baie, sw])
    db.session.commit()

    def fiche(e):
        return client.get(f'/inventory/{e.id}').get_data(as_text=True)

    b = fiche(vm)
    assert 'Hyperviseur' in b and 'Adresse IP' in b and 'Continuité' in b
    assert 'Sauvegarde 2' in b
    assert 'N° de série' not in b        # une VM ne s'achète pas
    assert 'Protocoles' not in b

    b = fiche(ph)
    assert 'N° de série' in b and 'PRA / PCA' in b and 'Continuité' in b
    assert 'Adresse IP' in b             # un serveur physique en a une aussi
    assert 'Protocoles' not in b and 'Hyperviseur' not in b

    b = fiche(nas)
    assert 'Protocoles' in b and 'N° de série' in b and 'Adresse IP' in b
    assert 'Usage / données stockées' in b

    # Une baie de stockage se décrit comme un NAS et s'achète comme un serveur.
    b = fiche(baie)
    assert 'Protocoles' in b and 'N° de série' in b and 'Adresse IP' in b
    assert 'PRA / PCA' in b
    assert 'Hyperviseur' not in b

    # Un équipement réseau : du matériel, une adresse, des ports — pas de
    # volumétrie ni de services utilisateurs.
    b = fiche(sw)
    assert 'N° de série' in b and 'Adresse IP' in b and 'VLAN' in b
    assert 'Nombre de ports' in b
    assert 'Protocoles' not in b and 'Hyperviseur' not in b
