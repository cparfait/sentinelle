"""Tests de l'API SoftInventory (GET /api/equipment) : activation, clé, format.

Contrat attendu par SoftInventory : tableau JSON trié par nom, auth
`Authorization: Bearer <clé>`, filtre `?kind=vm|physical|nas`.

Sentinelle DÉTIENT le parc ; SoftInventory n'en garde qu'une référence, de quoi
dire « ce logiciel tourne là » sans ressaisir l'IP ni l'hyperviseur.
"""
from app import db
from app.models import Equipment


def _seed():
    db.session.add(Equipment(name='SRV-WEB', kind='vm', environment='prod',
                             os='Debian', os_version='12', ip_address='10.0.0.5',
                             hypervisor='Proxmox', criticality=3))
    db.session.add(Equipment(name='BAIE-NAS', kind='nas', environment='prod'))
    db.session.add(Equipment(name='ANCIEN', kind='vm', environment='decommissioned'))
    db.session.commit()


def test_desactive_renvoie_503(app):
    app.config['INVENTORY_API_ENABLED'] = False
    app.config['INVENTORY_API_TOKEN'] = 'k'
    assert app.test_client().get('/api/equipment').status_code == 503


def test_sans_cle_ou_mauvaise_cle_renvoie_401(app):
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = 'bonne-cle'
    c = app.test_client()
    assert c.get('/api/equipment').status_code == 401
    assert c.get('/api/equipment',
                 headers={'Authorization': 'Bearer mauvaise'}).status_code == 401


def test_cle_absente_de_la_configuration_renvoie_503(app):
    # Activée mais sans clé : on refuse, on n'ouvre pas. Le mode de défaillance
    # d'une garde est le refus.
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = ''
    assert app.test_client().get('/api/equipment').status_code == 503


def test_rend_le_parc_trie_par_nom(app):
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = 'bonne-cle'
    with app.app_context():
        _seed()
    r = app.test_client().get('/api/equipment',
                              headers={'Authorization': 'Bearer bonne-cle'})
    assert r.status_code == 200
    noms = [e['name'] for e in r.get_json()]
    assert noms == ['ANCIEN', 'BAIE-NAS', 'SRV-WEB']


def test_le_decommissionne_sort_aussi(app):
    # Un logiciel peut encore pointer vers un serveur qu'on vient d'éteindre :
    # le faire disparaître du flux romprait le lien sans rien dire.
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = 'k'
    with app.app_context():
        _seed()
    r = app.test_client().get('/api/equipment', headers={'Authorization': 'Bearer k'})
    ancien = next(e for e in r.get_json() if e['name'] == 'ANCIEN')
    assert ancien['environment'] == 'decommissioned'


def test_filtre_par_type(app):
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = 'k'
    with app.app_context():
        _seed()
    c = app.test_client()
    r = c.get('/api/equipment?kind=nas', headers={'Authorization': 'Bearer k'})
    assert [e['name'] for e in r.get_json()] == ['BAIE-NAS']
    # Un filtre inconnu est IGNORÉ plutôt que refusé : une URL bricolée rend la
    # liste entière, elle ne casse pas l'import du consommateur.
    r = c.get('/api/equipment?kind=nimportequoi', headers={'Authorization': 'Bearer k'})
    assert len(r.get_json()) == 3


def test_le_contrat_porte_les_champs_attendus(app):
    app.config['INVENTORY_API_ENABLED'] = True
    app.config['INVENTORY_API_TOKEN'] = 'k'
    with app.app_context():
        _seed()
    r = app.test_client().get('/api/equipment', headers={'Authorization': 'Bearer k'})
    srv = next(e for e in r.get_json() if e['name'] == 'SRV-WEB')
    assert srv['kind'] == 'vm'
    assert srv['kind_label'] == 'VM'
    assert srv['os'] == 'Debian'
    assert srv['ip_address'] == '10.0.0.5'
    assert srv['hypervisor'] == 'Proxmox'
    assert srv['criticality'] == 3
    # Chaînes vides et non null : un client qui lit `.os.length` ne doit pas
    # tomber sur None. Seule la criticité reste nullable — c'est un entier.
    nas = next(e for e in r.get_json() if e['name'] == 'BAIE-NAS')
    assert nas['os'] == '' and nas['ip_address'] == ''
    assert nas['criticality'] is None
