"""Une mise à jour désigne sa cible par son nom ET par un lien : le lien se
pose à la saisie quand le nom est celui d'une fiche, et au démarrage pour
l'existant. Le nom reste : une mise à jour peut viser un élément hors
inventaire."""
from app import db, _migrate_data
from app.models import SystemUpdate, Software, Equipment


def _fiches():
    sw = Software(name='GLPI')
    eq = Equipment(name='srv-glpi', kind='vm')
    db.session.add_all([sw, eq])
    db.session.commit()
    return sw, eq


def test_le_nom_d_un_logiciel_relie_la_mise_a_jour(client):
    sw, _eq = _fiches()
    client.post('/updates/create', data={'name': 'glpi', 'status': 'up_to_date'},
                follow_redirects=True)
    u = SystemUpdate.query.first()
    assert u.software_id == sw.id and u.equipment_id is None
    assert f'/inventory/logiciels/{sw.id}' in client.get(f'/updates/{u.id}').get_data(as_text=True)
    # ... et le logiciel la compte dans son statut et son onglet Suivi.
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert f'/updates/{u.id}' in html


def test_le_nom_d_un_equipement_relie_sans_choix_explicite(client):
    _sw, eq = _fiches()
    client.post('/updates/create', data={'name': 'SRV-GLPI', 'status': 'up_to_date'},
                follow_redirects=True)
    u = SystemUpdate.query.first()
    assert u.equipment_id == eq.id and u.software_id is None


def test_l_equipement_choisi_prime_sur_le_nom(client):
    sw, eq = _fiches()
    autre = Equipment(name='srv-autre', kind='vm')
    db.session.add(autre)
    db.session.commit()
    client.post('/updates/create', data={'name': 'GLPI', 'status': 'up_to_date',
                                         'equipment_id': str(autre.id)}, follow_redirects=True)
    u = SystemUpdate.query.first()
    assert u.software_id == sw.id and u.equipment_id == autre.id


def test_modifier_le_nom_repose_le_lien(client):
    sw, eq = _fiches()
    u = SystemUpdate(name='GLPI', software_id=sw.id)
    db.session.add(u)
    db.session.commit()
    client.post(f'/updates/{u.id}/edit', data={'name': 'Hors inventaire', 'status': 'up_to_date'},
                follow_redirects=True)
    assert u.software_id is None and u.equipment_id is None and u.name == 'Hors inventaire'


def test_la_migration_relie_par_nom_sans_homonyme(app):
    sw, eq = _fiches()
    db.session.add(Software(name='Paie'))
    db.session.add(Software(name='paie'))
    db.session.add_all([SystemUpdate(name='glpi'), SystemUpdate(name='srv-glpi'),
                        SystemUpdate(name='Paie'), SystemUpdate(name='Windows Server')])
    db.session.commit()
    _migrate_data()
    a, b, c, d = SystemUpdate.query.order_by(SystemUpdate.id).all()
    assert a.software_id == sw.id
    assert b.equipment_id == eq.id
    assert c.software_id is None                # deux homonymes
    assert d.software_id is None and d.equipment_id is None
