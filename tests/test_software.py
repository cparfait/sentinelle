"""Tests Lot 2 : inventaire Logiciels métiers, liens serveurs (M:N), statut MAJ
agrégé et migration du catalogue applications (Asset) vers Software."""
from app import db, _migrate_data
from app.models import Software, Supplier, Equipment, Contract, Asset, SystemUpdate


def test_create_software_multi_serveurs(client):
    sup = Supplier(name='Éditeur')
    e1 = Equipment(name='A', kind='vm')
    e2 = Equipment(name='B', kind='vm')
    ct = Contract(name='Licence')
    db.session.add_all([sup, e1, e2, ct])
    db.session.commit()
    r = client.post('/inventory/logiciels/create', data={
        'name': 'Genesis', 'supplier_id': str(sup.id), 'contract_id': str(ct.id),
        'is_saas': 'on', 'equipment_ids': [str(e1.id), str(e2.id)]}, follow_redirects=True)
    assert r.status_code == 200
    sw = Software.query.filter_by(name='Genesis').first()
    assert sw.is_saas is True and sw.supplier_id == sup.id and sw.contract_id == ct.id
    assert {e.name for e in sw.equipments} == {'A', 'B'}
    # backref côté équipement (logiciels installés)
    assert sw in e1.software_list.all()


def test_edit_remplace_serveurs(client):
    e1 = Equipment(name='A', kind='vm'); e2 = Equipment(name='B', kind='vm')
    db.session.add_all([e1, e2]); db.session.commit()
    client.post('/inventory/logiciels/create',
                data={'name': 'GX', 'equipment_ids': [str(e1.id)]}, follow_redirects=True)
    sw = Software.query.filter_by(name='GX').first()
    client.post(f'/inventory/logiciels/{sw.id}/edit',
                data={'name': 'GX', 'equipment_ids': [str(e2.id)]}, follow_redirects=True)
    db.session.expire(sw)
    assert [e.name for e in sw.equipments] == ['B']


def test_computed_status_depuis_updates(app):
    sw = Software(name='S'); db.session.add(sw); db.session.commit()
    assert sw.computed_status() == 'success'
    db.session.add(SystemUpdate(name='u', status='update_available', software_id=sw.id))
    db.session.commit()
    assert sw.computed_status() == 'warning'
    db.session.add(SystemUpdate(name='u2', status='critical', software_id=sw.id))
    db.session.commit()
    assert sw.computed_status() == 'danger'


def test_migration_asset_application(app):
    db.session.add(Asset(name='GLPI', asset_type='application', description='Parc'))
    db.session.add(Asset(name='Bidule', asset_type='divers'))
    db.session.commit()
    _migrate_data()
    assert [s.name for s in Software.query.all()] == ['GLPI']   # 'divers' non migré
    _migrate_data()                                             # idempotent
    assert Software.query.count() == 1


def test_delete_software(client):
    sw = Software(name='Z'); db.session.add(sw); db.session.commit()
    client.post(f'/inventory/logiciels/{sw.id}/delete', follow_redirects=True)
    db.session.expire(sw)
    assert sw.is_active is False


def test_quick_create_application(client):
    r = client.post('/inventory/logiciels/quick-create', data={'name': 'SIRH'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] and j['name'] == 'SIRH' and isinstance(j['id'], int)
    assert Software.query.filter_by(name='SIRH').first() is not None
    assert client.post('/inventory/logiciels/quick-create', data={'name': ''}).status_code == 400


def test_revue_pointe_sur_inventaire_applications(client):
    """L'« Application métier » de la revue est un select alimente par l'inventaire
    Logiciels, avec le bouton + (ajout rapide d'une application)."""
    db.session.add_all([Software(name='GED'), Software(name='Finances')])
    db.session.commit()
    html = client.get('/reviews/create').get_data(as_text=True)
    # select (et non plus input libre) rattache a l'inventaire + quick-add
    assert '<select name="application"' in html
    assert '>GED<' in html and '>Finances<' in html
    assert 'qaModalSoftware' in html


def test_revue_conserve_application_hors_inventaire(client):
    """Une revue dont l'application n'existe pas (ou plus) dans l'inventaire garde
    sa valeur (option « hors inventaire ») a l'edition."""
    from app.models import AccessReview
    rv = AccessReview(application='AppLegacy', frequency_days=365, status='pending')
    db.session.add(rv); db.session.commit()
    html = client.get(f'/reviews/{rv.id}/edit').get_data(as_text=True)
    assert 'AppLegacy' in html and 'hors inventaire' in html
