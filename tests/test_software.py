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
