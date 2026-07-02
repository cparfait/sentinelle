"""Tests Lot 1 : contrats multi-équipements, migration de l'ancien lien unique,
ajout rapide de fournisseur (AJAX) et fiche fournisseur (impacts)."""
from app import db, _migrate_data
from app.models import Supplier, Equipment, Contract


def test_contract_multi_equipements(client):
    sup = Supplier(name='Dell')
    e1 = Equipment(name='S1', kind='vm')
    e2 = Equipment(name='S2', kind='nas')
    db.session.add_all([sup, e1, e2])
    db.session.commit()
    r = client.post('/contracts/create', data={
        'name': 'Maint', 'kind': 'maintenance', 'supplier_id': str(sup.id),
        'equipment_ids': [str(e1.id), str(e2.id)], 'notice_days': '0'},
        follow_redirects=True)
    assert r.status_code == 200
    ct = Contract.query.filter_by(name='Maint').first()
    assert {e.name for e in ct.equipments} == {'S1', 'S2'}
    # backref côté équipement (vue 360°) toujours fonctionnel
    assert ct in e1.contracts.all()


def test_edit_remplace_les_equipements(client):
    e1 = Equipment(name='A', kind='vm'); e2 = Equipment(name='B', kind='vm')
    db.session.add_all([e1, e2]); db.session.commit()
    client.post('/contracts/create', data={'name': 'C', 'equipment_ids': [str(e1.id)]},
                follow_redirects=True)
    ct = Contract.query.filter_by(name='C').first()
    assert [e.name for e in ct.equipments] == ['A']
    client.post(f'/contracts/{ct.id}/edit', data={'name': 'C', 'equipment_ids': [str(e2.id)]},
                follow_redirects=True)
    db.session.expire(ct)
    assert [e.name for e in ct.equipments] == ['B']


def test_migration_ancien_equipment_id(app):
    e = Equipment(name='LegacySRV', kind='physical')
    db.session.add(e); db.session.commit()
    ct = Contract(name='Ancien')
    ct.equipment_id = e.id          # ancien lien direct, sans ligne d'association
    db.session.add(ct); db.session.commit()
    assert ct.equipments == []
    _migrate_data()                 # doit recopier equipment_id -> contract_equipment
    db.session.expire(ct)
    assert [x.name for x in ct.equipments] == ['LegacySRV']
    _migrate_data()                 # idempotent : pas de doublon
    db.session.expire(ct)
    assert len(ct.equipments) == 1


def test_quick_create_fournisseur(client):
    r = client.post('/suppliers/quick-create', data={'name': 'HP', 'email': 'a@b.fr'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] and j['name'] == 'HP' and isinstance(j['id'], int)
    assert Supplier.query.filter_by(name='HP').first() is not None
    # nom vide -> 400
    assert client.post('/suppliers/quick-create', data={'name': ''}).status_code == 400


def test_quick_create_contrat(client):
    r = client.post('/contracts/quick-create', data={'name': 'Office 365', 'end_date': '2027-01-31'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] and j['name'] == 'Office 365' and isinstance(j['id'], int)
    ct = Contract.query.filter_by(name='Office 365').first()
    assert ct is not None and ct.end_date.isoformat() == '2027-01-31'
    assert client.post('/contracts/quick-create', data={'name': ''}).status_code == 400


def test_quick_create_equipement(client):
    r = client.post('/inventory/quick-create', data={'name': 'SRV-QA', 'kind': 'physical'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] and j['id'] and j['label'] == 'SRV-QA (Serveur physique)'
    eq = Equipment.query.filter_by(name='SRV-QA').first()
    assert eq is not None and eq.kind == 'physical'
    # type invalide -> repli sur 'vm'
    r2 = client.post('/inventory/quick-create', data={'name': 'SRV-X', 'kind': 'bogus'})
    assert r2.get_json()['ok'] and Equipment.query.filter_by(name='SRV-X').first().kind == 'vm'
    assert client.post('/inventory/quick-create', data={'name': ''}).status_code == 400


def test_formulaires_affichent_bouton_ajout_rapide(client):
    """Le + (ajout rapide) est present sur les formulaires concernes."""
    # Logiciel : fournisseur, contrat, serveur.
    html = client.get('/inventory/logiciels/create').get_data(as_text=True)
    assert 'qaModalSupplier' in html and 'qaModalContract' in html and 'qaModalEquipment' in html
    # Contrat : fournisseur + equipement.
    html = client.get('/contracts/create').get_data(as_text=True)
    assert 'qaModalSupplier' in html and 'qaModalEquipment' in html
    # Equipement : fournisseur.
    html = client.get('/inventory/create').get_data(as_text=True)
    assert 'qaModalSupplier' in html
    # Certificat (partial _equipment_select) : equipement.
    html = client.get('/certificates/create').get_data(as_text=True)
    assert 'qaModalEquipment' in html


def test_fiche_fournisseur_impacts(client):
    sup = Supplier(name='OVH')
    db.session.add(sup); db.session.commit()
    e = Equipment(name='SRVWEB', kind='physical', supplier_id=sup.id)
    ct = Contract(name='Hebergement', supplier_id=sup.id)
    db.session.add_all([e, ct]); db.session.commit()
    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    assert html.count('SRVWEB') and 'Hebergement' in html
    assert 'Matériel couvert' in html and 'Contrats' in html
