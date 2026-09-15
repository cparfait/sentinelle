"""L'inventaire se lit en deux familles : Serveurs et Réseau.

Un switch n'est pas un serveur. Les réunir sous « Matériel » obligeait à cinq
onglets et à un titre qui énumère ; chaque famille a donc son entrée de menu et
ses propres onglets, sur la même table et le même écran.
"""
from app import db
from app.models import (Equipment, EQUIPMENT_KIND_LABELS, EQUIPMENT_FAMILIES,
                        equipment_family)


def _parc():
    db.session.add_all([
        Equipment(name='SRV-APP01', kind='vm'),
        Equipment(name='ESX-01', kind='physical'),
        Equipment(name='NAS-BACKUP', kind='nas'),
        Equipment(name='BAIE-SAN-01', kind='storage'),
        Equipment(name='SW-CORE-01', kind='network'),
        Equipment(name='FW-EDGE', kind='network'),
    ])
    db.session.commit()


# ── Les natures ──

def test_les_cinq_natures_existent(client):
    assert set(EQUIPMENT_KIND_LABELS) == {'vm', 'physical', 'nas', 'storage', 'network'}
    assert EQUIPMENT_KIND_LABELS['storage'] == 'Baie de stockage'
    assert EQUIPMENT_KIND_LABELS['network'] == 'Équipement réseau'


def test_la_baie_va_aux_serveurs_le_switch_au_reseau(client):
    """La baie vit dans la même salle que les serveurs, se garantit et se
    maintient pareil : c'est auprès d'eux qu'on la cherche."""
    assert equipment_family('storage') == 'serveurs'
    assert equipment_family('network') == 'reseau'
    # Une nature inconnue ne rend pas la fiche invisible.
    assert equipment_family('licorne') == 'serveurs'


# ── Les deux écrans ──

def test_chaque_famille_ne_montre_que_la_sienne(client):
    _parc()
    serveurs = client.get('/inventory/').get_data(as_text=True)
    assert 'BAIE-SAN-01' in serveurs and 'SRV-APP01' in serveurs
    assert 'SW-CORE-01' not in serveurs and 'FW-EDGE' not in serveurs

    reseau = client.get('/inventory/?famille=reseau').get_data(as_text=True)
    assert 'SW-CORE-01' in reseau and 'FW-EDGE' in reseau
    assert 'SRV-APP01' not in reseau and 'BAIE-SAN-01' not in reseau


def test_une_famille_inconnue_retombe_sur_les_serveurs(client):
    _parc()
    b = client.get('/inventory/?famille=licornes').get_data(as_text=True)
    assert 'SRV-APP01' in b and 'SW-CORE-01' not in b


def test_un_onglet_de_l_autre_famille_est_ignore(client):
    """Demander ?kind=network depuis les Serveurs ne doit pas rendre une liste
    vide sans explication : la nature hors famille est simplement écartée."""
    _parc()
    b = client.get('/inventory/?kind=network').get_data(as_text=True)
    assert 'SRV-APP01' in b and 'BAIE-SAN-01' in b


def test_le_reseau_n_affiche_pas_d_onglets(client):
    """Une famille d'une seule nature n'a pas d'onglets : ils ne diraient rien
    que le titre ne dise déjà."""
    _parc()
    b = client.get('/inventory/?famille=reseau').get_data(as_text=True)
    assert 'Switches, pare-feu' in b
    assert 'seg-tab-count' not in b
    # Côté serveurs, les quatre natures ont le leur.
    b = client.get('/inventory/').get_data(as_text=True)
    assert 'Baie de stockage' in b and 'seg-tab-count' in b


# ── La création ──

def test_creer_depuis_le_reseau_ne_propose_pas_vm(client):
    """Sans cela, créer un switch depuis l'écran Réseau proposerait « VM » par
    défaut, et la fiche partirait dans l'autre famille."""
    b = client.get('/inventory/create?famille=reseau').get_data(as_text=True)
    assert 'Équipement réseau' in b
    assert '>VM<' not in b and 'Baie de stockage' not in b

    b = client.get('/inventory/create').get_data(as_text=True)
    assert '>VM<' in b and 'Baie de stockage' in b
    assert 'Équipement réseau' not in b


def test_une_fiche_existante_peut_changer_de_famille(client):
    """La liste complète reste ouverte à la modification : une fiche mal classée
    doit pouvoir changer de camp."""
    sw = Equipment(name='MAL-CLASSE', kind='vm')
    db.session.add(sw)
    db.session.commit()
    b = client.get(f'/inventory/{sw.id}/edit').get_data(as_text=True)
    assert 'Équipement réseau' in b and '>VM<' in b


def test_creation_d_un_switch(client):
    client.post('/inventory/create', data={
        'kind': 'network', 'name': 'SW-ACCES-03', 'ip_address': '10.0.0.3',
        'vlan': '10', 'ports': '24', 'manufacturer_model': 'Aruba 6100',
        'location': 'Salle serveur, baie 2',
        'management_url': 'https://10.0.0.3'}, follow_redirects=True)
    e = Equipment.query.filter_by(name='SW-ACCES-03').one()
    assert e.kind == 'network' and e.ports == 24
    assert e.location == 'Salle serveur, baie 2'
    assert e.management_url == 'https://10.0.0.3'
    assert e.famille() == 'reseau'


def test_une_nature_inventee_retombe_sur_vm(client):
    """Un POST forgé ne doit pas inscrire une nature qu'aucun écran ne sait
    relire."""
    client.post('/inventory/create', data={'kind': 'licorne', 'name': 'BIDON'},
                follow_redirects=True)
    assert Equipment.query.filter_by(name='BIDON').one().kind == 'vm'


# ── Ce que chaque nature porte ──

def test_les_groupes_decident_de_ce_qui_s_affiche(client):
    vm = Equipment(name='V', kind='vm')
    sw = Equipment(name='S', kind='network')
    baie = Equipment(name='B', kind='storage')
    # Le matériel s'achète ; une VM, non.
    assert vm.porte('materiel') is False
    assert sw.porte('materiel') is True and baie.porte('materiel') is True
    # Les ports ne caractérisent que l'équipement réseau.
    assert sw.porte('ports') is True and baie.porte('ports') is False
    # La volumétrie ne concerne que ce qui stocke.
    assert baie.porte('stockage') is True and sw.porte('stockage') is False
    # Tout ce qui a une adresse a une section Réseau — y compris le physique,
    # dont l'absence était un oubli.
    assert Equipment(name='P', kind='physical').porte('reseau') is True


def test_l_ajout_rapide_propose_toutes_les_natures(client):
    """La fenêtre d'ajout rapide est une macro Jinja : elle n'hérite pas du
    contexte, d'où une variable globale. Sans cela, la liste y serait vide."""
    b = client.get('/inventory/create').get_data(as_text=True)
    assert 'qaModalEquipment' not in b or 'Équipement réseau' in b
    b = client.get('/certificates/create').get_data(as_text=True)
    assert 'Baie de stockage' in b and 'Équipement réseau' in b


# ── L'import de tableur ──

def test_l_onglet_d_un_tableur_donne_la_nature(client):
    """Les formes les plus précises d'abord : « baie de stockage » contient
    « stockage », et un test plus large gagnerait la course sur un test juste."""
    from app.inventory_import import _detect_kind
    assert _detect_kind('Baies de stockage') == 'storage'
    assert _detect_kind('SAN') == 'storage'
    assert _detect_kind('Switches') == 'network'
    assert _detect_kind('Pare-feu') == 'network'
    assert _detect_kind('Matériel réseau') == 'network'
    assert _detect_kind('Bornes WiFi') == 'network'
    assert _detect_kind('NAS') == 'nas'
    assert _detect_kind('VM') == 'vm'
    assert _detect_kind('Serveurs physiques') == 'physical'
    assert _detect_kind('Feuille1') is None


def test_les_familles_couvrent_toutes_les_natures(client):
    """Une nature ajoutée sans famille deviendrait invisible dans les deux
    écrans : le test le dirait avant l'utilisateur."""
    rangees = {k for natures in EQUIPMENT_FAMILIES.values() for k in natures}
    assert rangees == set(EQUIPMENT_KIND_LABELS)
