"""Un compte se rattache à ce qu'il sert : logiciel, équipement, fournisseur.
Liens posés depuis le formulaire, rapprochement par nom du service au
démarrage, et les fiches d'en face listent leurs comptes."""
from app import db, _migrate_data
from app.models import Account, Software, Equipment, Supplier


def _fiches():
    sw = Software(name='GLPI')
    eq = Equipment(name='srv-glpi', kind='vm')
    sup = Supplier(name='OVHcloud')
    db.session.add_all([sw, eq, sup])
    db.session.commit()
    return sw, eq, sup


def test_le_formulaire_propose_les_trois_rattachements(client):
    _fiches()
    html = client.get('/accounts/create').get_data(as_text=True)
    for champ in ('software_id', 'equipment_id', 'supplier_id'):
        assert f'name="{champ}"' in html
    assert 'qaModalSoftware' in html and 'qaModalEquipment' in html and 'qaModalSupplier' in html


def test_un_compte_cree_avec_ses_liens_et_les_fiches_d_en_face(client):
    sw, eq, sup = _fiches()
    client.post('/accounts/create', data={'service_name': 'GLPI superadmin', 'username': 'glpi',
                                          'software_id': str(sw.id), 'equipment_id': str(eq.id),
                                          'supplier_id': str(sup.id)}, follow_redirects=True)
    a = Account.query.first()
    assert (a.software_id, a.equipment_id, a.supplier_id) == (sw.id, eq.id, sup.id)
    html = client.get(f'/accounts/{a.id}').get_data(as_text=True)
    assert f'/inventory/logiciels/{sw.id}' in html and f'/inventory/{eq.id}' in html \
        and f'/suppliers/{sup.id}' in html
    assert f'/accounts/{a.id}' in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert f'/accounts/{a.id}' in client.get(f'/inventory/{eq.id}').get_data(as_text=True)
    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    assert 'ong-comptes' in html and f'/accounts/{a.id}' in html


def test_modifier_retire_ou_change_un_lien(client):
    sw, eq, sup = _fiches()
    a = Account(service_name='GLPI superadmin', username='glpi', software_id=sw.id, supplier_id=sup.id)
    db.session.add(a)
    db.session.commit()
    client.post(f'/accounts/{a.id}/edit', data={'service_name': 'GLPI superadmin', 'username': 'glpi',
                                                'equipment_id': str(eq.id)}, follow_redirects=True)
    assert (a.software_id, a.equipment_id, a.supplier_id) == (None, eq.id, None)


def test_un_identifiant_qui_ne_designe_rien_ne_se_pose_pas(client):
    sw, _eq, _sup = _fiches()
    sw.is_active = False
    db.session.commit()
    client.post('/accounts/create', data={'service_name': 'X', 'username': 'x',
                                          'software_id': str(sw.id), 'equipment_id': '999'},
                follow_redirects=True)
    a = Account.query.first()
    assert a.software_id is None and a.equipment_id is None


# ── Migration des comptes existants ──

def test_la_migration_relie_par_nom_du_service(app):
    sw, eq, sup = _fiches()
    db.session.add_all([Account(service_name='glpi', username='a'),          # -> logiciel
                        Account(service_name='SRV-GLPI', username='b'),      # -> equipement
                        Account(service_name='OVH Manager', username='c'),   # rien
                        Account(service_name='GLPI', username='d', supplier_id=sup.id)])  # deja rattache
    db.session.commit()
    _migrate_data()
    a, b, c, d = Account.query.order_by(Account.id).all()
    assert a.software_id == sw.id and a.equipment_id is None
    assert b.equipment_id == eq.id and b.software_id is None
    assert c.software_id is None and c.equipment_id is None
    assert d.software_id is None and d.supplier_id == sup.id


def test_la_migration_ne_tranche_pas_entre_deux_homonymes(app):
    db.session.add_all([Software(name='GLPI'), Software(name='glpi'),
                        Account(service_name='GLPI', username='a')])
    db.session.commit()
    _migrate_data()
    assert Account.query.first().software_id is None
