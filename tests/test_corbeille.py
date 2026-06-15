"""Corbeille : les equipements desactives doivent etre visibles, restaurables
et purgeables comme les autres categories (coherence avec le badge sidebar)."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import Equipment, Certificate, Backup, SystemUpdate


def _equipement_supprime(name='SRV-CORB-01'):
    e = Equipment(name=name, kind='vm', is_active=False)
    db.session.add(e)
    db.session.commit()
    return e


def test_equipement_supprime_visible_dans_la_corbeille(app, client):
    e = _equipement_supprime()
    r = client.get('/trash')
    assert r.status_code == 200
    body = r.data.decode('utf-8')
    assert 'Inventaire' in body
    assert e.name in body


def test_restauration_equipement(app, client):
    e = _equipement_supprime()
    r = client.post('/trash/restore',
                    data={'entity_type': 'equipment', 'entity_id': e.id},
                    follow_redirects=True)
    assert r.status_code == 200
    assert 'Élément restauré.' in r.data.decode('utf-8')
    assert db.session.get(Equipment, e.id).is_active is True


def test_purge_equipement_detache_les_elements_lies(app, client):
    """La purge supprime l'equipement et met a NULL les equipment_id des
    certificats/backups/mises a jour lies (SQLite n'applique pas les FK)."""
    e = _equipement_supprime()
    cert = Certificate(service_name='Intranet', domain='intra.exemple.fr',
                       expiry_date=datetime.now(timezone.utc).date() + timedelta(days=90),
                       equipment_id=e.id)
    bkp = Backup(service_name='Veeam SRV-CORB-01', frequency='daily', equipment_id=e.id)
    upd = SystemUpdate(name='GLPI', equipment_id=e.id)
    db.session.add_all([cert, bkp, upd])
    db.session.commit()

    r = client.post('/trash/purge-one',
                    data={'entity_type': 'equipment', 'entity_id': e.id},
                    follow_redirects=True)
    assert r.status_code == 200
    assert db.session.get(Equipment, e.id) is None
    assert db.session.get(Certificate, cert.id).equipment_id is None
    assert db.session.get(Backup, bkp.id).equipment_id is None
    assert db.session.get(SystemUpdate, upd.id).equipment_id is None


def test_vider_la_corbeille_inclut_les_equipements(app, client):
    e = _equipement_supprime()
    r = client.post('/trash/purge', follow_redirects=True)
    assert r.status_code == 200
    assert db.session.get(Equipment, e.id) is None


def test_badge_corbeille_couvre_les_memes_categories_que_la_page():
    """Toute categorie comptee dans le badge sidebar (inject_nav_counts) doit
    avoir une entree dans SPECS, sinon des elements comptes sont invisibles."""
    from app.trash import SPECS
    cats = {s['cat'] for s in SPECS.values()}
    assert {'accounts', 'certificates', 'domains', 'backups', 'tests',
            'reviews', 'updates', 'inventory'} <= cats
