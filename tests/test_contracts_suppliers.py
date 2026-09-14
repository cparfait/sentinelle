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


# ── L'annuaire tient les contacts, les fiches logiciel les remontent ──

def test_contacts_editeur_enregistres_et_herites(client):
    """Les coordonnées ne se saisissent QU'ICI : la fiche logiciel les affiche
    en lecture seule. La recopier fiche par fiche garantirait des numéros
    divergents."""
    from app.models import Software
    client.post('/suppliers/create', data={
        'name': 'Berger-Levrault', 'kind': 'editor',
        'support_url': 'https://support.bl.fr', 'support_phone': '0820000000',
        'support_email': 'assistance@bl.fr', 'customer_ref': 'CLI-42',
        'hours': 'lundi au vendredi 8h-17h', 'hours2': 'samedi 8h-12h',
        'city': 'Boulogne', 'website': 'https://bl.fr',
        'commercial_contact': 'DUPONT', 'commercial_email': 'dupont@bl.fr',
        'commercial2_contact': 'MOREAU', 'commercial2_phone': '0601020304',
        'admin_contact': 'Service facturation', 'admin_email': 'factu@bl.fr',
        'dpo_contact': 'DPO BL', 'dpo_email': 'dpo@bl.fr',
    }, follow_redirects=True)
    sup = Supplier.query.filter_by(name='Berger-Levrault').one()
    assert sup.support_email == 'assistance@bl.fr' and sup.hours2 == 'samedi 8h-12h'
    assert sup.commercial_contact == 'DUPONT'
    assert sup.commercial_contact2 == 'MOREAU' and sup.commercial_phone2 == '0601020304'
    assert sup.admin_email == 'factu@bl.fr' and sup.dpo_email == 'dpo@bl.fr'
    assert sup.has_contacts() is True

    sw = Software(name='e-Enfance', supplier_id=sup.id, gdpr_personal_data=True)
    db.session.add(sw); db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'MOREAU' in html and 'factu@bl.fr' in html
    assert 'dpo@bl.fr' in html            # le DPO de l'éditeur, dans le volet RGPD
    assert 'CLI-42' in html               # le n° client, cherché juste avant d'appeler


def test_sans_contact_la_carte_ne_parait_pas(client):
    """Une carte pleine de tirets ne dit pas qui appeler, elle dit qu'on ne sait
    pas : elle ne s'affiche donc pas."""
    sup = Supplier(name='Sans contact')
    db.session.add(sup); db.session.commit()
    assert sup.has_contacts() is False
    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    assert 'person-lines-fill' not in html
