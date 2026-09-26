"""Tests Lot 2 : inventaire Logiciels métiers, liens serveurs (M:N), statut MAJ
agrégé et migration du catalogue applications (Asset) vers Software."""
from app import db, _migrate_data
from sqlalchemy import text

from app.models import Software, Supplier, Equipment, Contract, SystemUpdate


def test_create_software_multi_serveurs(client):
    sup = Supplier(name='Éditeur')
    e1 = Equipment(name='A', kind='vm')
    e2 = Equipment(name='B', kind='vm')
    ct = Contract(name='Licence')
    db.session.add_all([sup, e1, e2, ct])
    db.session.commit()
    r = client.post('/inventory/logiciels/create', data={
        'name': 'Genesis', 'supplier_id': str(sup.id), 'contract_ids': [str(ct.id)],
        'hosting': 'saas', 'equipment_ids': [str(e1.id), str(e2.id)]}, follow_redirects=True)
    assert r.status_code == 200
    sw = Software.query.filter_by(name='Genesis').first()
    assert sw.is_saas is True and sw.supplier_id == sup.id
    assert [c.name for c in sw.contracts] == ['Licence']
    assert {e.name for e in sw.equipments} == {'A', 'B'}
    # backref côté équipement (logiciels installés)
    assert sw in e1.software_list.all()


def test_create_software_docker(client):
    # le formulaire propose les trois regimes d'hebergement et le bouton Docker
    html = client.get('/inventory/logiciels/create').get_data(as_text=True)
    assert 'value="on_premise"' in html and 'value="saas"' in html and 'value="hybride"' in html
    assert 'name="is_docker"' in html and 'icon-docker' in html
    r = client.post('/inventory/logiciels/create',
                    data={'name': 'Portainer', 'hosting': 'on_premise', 'is_docker': 'on'},
                    follow_redirects=True)
    assert r.status_code == 200
    sw = Software.query.filter_by(name='Portainer').first()
    assert sw.is_docker is True and sw.is_saas is False
    # Docker est cumulable avec le SaaS
    client.post(f'/inventory/logiciels/{sw.id}/edit',
                data={'name': 'Portainer', 'hosting': 'saas', 'is_docker': 'on'},
                follow_redirects=True)
    db.session.expire(sw)
    assert sw.is_saas is True and sw.is_docker is True
    # decocher Docker et repasser on premise remet les deux drapeaux a False
    client.post(f'/inventory/logiciels/{sw.id}/edit',
                data={'name': 'Portainer', 'hosting': 'on_premise'}, follow_redirects=True)
    db.session.expire(sw)
    assert sw.is_docker is False and sw.is_saas is False


def test_hybride_echappe_au_parc(client):
    """« Hybride » : une part chez nous, une part dehors. Le booleen historique
    is_saas dit « echappe au parc » -- il doit donc etre vrai."""
    client.post('/inventory/logiciels/create',
                data={'name': 'Portail Citoyen', 'hosting': 'hybride'},
                follow_redirects=True)
    sw = Software.query.filter_by(name='Portail Citoyen').one()
    assert sw.hosting == 'hybride' and sw.is_saas is True


def test_liste_filtre_hebergement(client):
    """Onglets Docker / SaaS / On premise : Docker est un attribut cumulable, un
    logiciel conteneurise apparait aussi dans son onglet d'hebergement. Un
    logiciel HYBRIDE parait dans les deux onglets d'hebergement -- l'exclure de
    l'un cacherait la moitie de ce qu'il est."""
    db.session.add_all([Software(name='ConteneurGED', is_docker=True),
                        Software(name='CloudRH', hosting='saas'),
                        Software(name='CloudDockerPaie', hosting='saas', is_docker=True),
                        Software(name='PortailMixte', hosting='hybride'),
                        Software(name='LocalFinances')])
    db.session.commit()
    html = client.get('/inventory/logiciels/?host=docker').get_data(as_text=True)
    assert 'ConteneurGED' in html and 'CloudDockerPaie' in html
    assert 'CloudRH' not in html and 'LocalFinances' not in html
    html = client.get('/inventory/logiciels/?host=saas').get_data(as_text=True)
    assert 'CloudRH' in html and 'CloudDockerPaie' in html and 'PortailMixte' in html
    assert 'ConteneurGED' not in html
    html = client.get('/inventory/logiciels/?host=onprem').get_data(as_text=True)
    assert 'LocalFinances' in html and 'ConteneurGED' in html and 'PortailMixte' in html
    assert 'CloudRH' not in html and 'CloudDockerPaie' not in html
    # sans filtre : tout est visible
    html = client.get('/inventory/logiciels/').get_data(as_text=True)
    for n in ('ConteneurGED', 'CloudRH', 'CloudDockerPaie', 'PortailMixte', 'LocalFinances'):
        assert n in html


def test_edit_remplace_serveurs(client):
    e1 = Equipment(name='A', kind='vm')
    e2 = Equipment(name='B', kind='vm')
    db.session.add_all([e1, e2])
    db.session.commit()
    client.post('/inventory/logiciels/create',
                data={'name': 'GX', 'equipment_ids': [str(e1.id)]}, follow_redirects=True)
    sw = Software.query.filter_by(name='GX').first()
    client.post(f'/inventory/logiciels/{sw.id}/edit',
                data={'name': 'GX', 'equipment_ids': [str(e2.id)]}, follow_redirects=True)
    db.session.expire(sw)
    assert [e.name for e in sw.equipments] == ['B']


def test_computed_status_depuis_updates(app):
    sw = Software(name='S')
    db.session.add(sw)
    db.session.commit()
    assert sw.computed_status() == 'success'
    db.session.add(SystemUpdate(name='u', status='update_available', software_id=sw.id))
    db.session.commit()
    assert sw.computed_status() == 'warning'
    db.session.add(SystemUpdate(name='u2', status='critical', software_id=sw.id))
    db.session.commit()
    assert sw.computed_status() == 'danger'


def test_migration_asset_application(app):
    """Une base ancienne a encore la table asset (le modele n'existe plus) :
    ses applications rejoignent les logiciels, une seule fois."""
    db.session.execute(text(
        "CREATE TABLE asset (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, "
        "asset_type VARCHAR(20), description VARCHAR(256), is_active BOOLEAN, created_at DATETIME)"))
    db.session.execute(text(
        "INSERT INTO asset (name, asset_type, description, is_active) VALUES "
        "('GLPI', 'application', 'Parc', 1), ('Bidule', 'divers', NULL, 1)"))
    db.session.commit()
    _migrate_data()
    assert [s.name for s in Software.query.all()] == ['GLPI']   # 'divers' non migré
    _migrate_data()                                             # idempotent
    assert Software.query.count() == 1


def test_delete_software(client):
    sw = Software(name='Z')
    db.session.add(sw)
    db.session.commit()
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
    db.session.add(rv)
    db.session.commit()
    html = client.get(f'/reviews/{rv.id}/edit').get_data(as_text=True)
    assert 'AppLegacy' in html and 'hors inventaire' in html


# ── Ce qui vient de SoftInventory ne se modifie pas ici ─────────────────────
# Deux règles, une même raison : l'outil qui DÉTIENT la donnée est le seul à
# pouvoir la changer. Réécrire ici ne tiendrait que jusqu'au prochain import.


def test_le_catalogue_se_cree_ici(client):
    """Le catalogue appartient à Sentinelle : rien ne refuse plus une création,
    et la fiche est entièrement modifiable — il n'y a plus d'import pour
    écraser la saisie."""
    r = client.get('/inventory/logiciels/create', follow_redirects=True)
    assert 'Ajouter un logiciel' in r.get_data(as_text=True)
    assert 'SoftInventory' not in r.get_data(as_text=True)
    client.post('/inventory/logiciels/create', data={'name': 'Saisi ici'},
                follow_redirects=True)
    assert Software.query.filter_by(name='Saisi ici').first() is not None
    # L'ajout rapide depuis un autre formulaire ne refuse plus non plus.
    r = client.post('/inventory/logiciels/quick-create', data={'name': 'Express'})
    assert r.status_code == 200
    assert Software.query.filter_by(name='Express').first() is not None


def test_une_fiche_locale_reste_entierement_modifiable(client):
    sw = Software(name='Local', responsible='MARTIN')
    db.session.add(sw)
    db.session.commit()
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={
        'name': 'Local renommé', 'responsible': 'DUPONT', 'hosting': 'saas'},
        follow_redirects=True)
    sw = Software.query.one()
    assert sw.name == 'Local renommé' and sw.responsible == 'DUPONT'


# ── Fiche enrichie : qualification, utilisateurs, RGPD ──

def test_creation_enregistre_la_qualification_et_le_rgpd(client):
    from app.models import Referential
    techno = Referential.query.filter_by(kind='technology', label='Web').one()
    client.post('/inventory/logiciels/create', data={
        'name': 'Concerto', 'hosting': 'hybride', 'lifecycle': 'fin_de_vie',
        'source_type': 'opensource', 'technology_id': str(techno.id),
        'auth_mode': 'mixte_ldap', 'auth_strong': 'on',
        'users_count': '120', 'users_max': '100',
        'service_date': '2019-03-01', 'internal_dev': 'on', 'no_server': 'on',
        'tech_responsible': 'DURAND', 'tech_responsible_email': 'durand@ville.fr',
        'no_contract_note': 'Marché porté par le CCAS',
        'gdpr_personal_data': 'on', 'gdpr_categories': 'état civil, NIR',
        'gdpr_registry_ref': 'T-014', 'gdpr_location': 'ue',
    }, follow_redirects=True)
    sw = Software.query.filter_by(name='Concerto').one()
    assert sw.lifecycle == 'fin_de_vie' and sw.source_type == 'opensource'
    assert sw.technology_id == techno.id and sw.auth_mode == 'mixte_ldap'
    assert sw.auth_strong is True and sw.internal_dev is True and sw.no_server is True
    assert sw.users_count == 120 and sw.users_max == 100
    assert sw.service_date.isoformat() == '2019-03-01'
    assert sw.tech_responsible_email == 'durand@ville.fr'
    assert sw.no_contract_note == 'Marché porté par le CCAS'
    assert sw.gdpr_personal_data is True and sw.gdpr_registry_ref == 'T-014'
    assert sw.gdpr_location == 'ue'


def test_valeur_de_liste_inconnue_retombe_sur_le_defaut(client):
    """Un POST forgé ne doit pas inscrire une valeur qu'aucun écran ne sait
    relire : le cycle de vie et l'hébergement retombent sur leur défaut, et le
    mode d'authentification sur « non renseigné »."""
    client.post('/inventory/logiciels/create', data={
        'name': 'Bidon', 'hosting': 'ailleurs', 'lifecycle': 'zombie',
        'source_type': 'magique', 'auth_mode': 'telepathie',
        'gdpr_location': 'lune'}, follow_redirects=True)
    sw = Software.query.filter_by(name='Bidon').one()
    assert sw.hosting == 'on_premise' and sw.lifecycle == 'production'
    assert sw.source_type == 'proprietaire' and sw.auth_mode is None
    assert sw.gdpr_location == 'inconnue'


def test_fin_de_vie_passe_le_statut_a_orange(client):
    """Un logiciel en fin de vie est une échéance : il lui faut un successeur.
    « Abandonné » n'en est plus une — il n'est plus en service."""
    fin = Software(name='Vieux', lifecycle='fin_de_vie')
    abandonne = Software(name='Retiré', lifecycle='abandonne')
    vivant = Software(name='Actuel', lifecycle='production')
    db.session.add_all([fin, abandonne, vivant])
    db.session.commit()
    assert fin.computed_status() == 'warning'
    assert abandonne.computed_status() == 'success'
    assert vivant.computed_status() == 'success'


def test_une_maj_critique_prime_sur_le_cycle_de_vie(client):
    sw = Software(name='Portail', lifecycle='fin_de_vie')
    db.session.add(sw)
    db.session.commit()
    db.session.add(SystemUpdate(name='Portail', software_id=sw.id, status='critical'))
    db.session.commit()
    assert sw.computed_status() == 'danger'


def test_depassement_de_licence(client):
    """None quand l'un des deux nombres manque : sans les deux, il n'y a rien à
    comparer, et répondre « non » laisserait croire qu'on a vérifié."""
    assert Software(name='A', users_count=120, users_max=100).over_licence() is True
    assert Software(name='B', users_count=80, users_max=100).over_licence() is False
    assert Software(name='C', users_count=80).over_licence() is None
    assert Software(name='D', users_max=100).over_licence() is None


def test_la_fiche_affiche_tout_ce_qu_elle_porte(client):
    """La fiche a été redessinée : grille dense en haut, cartes liées en bas.

    Le risque d'une refonte de gabarit n'est pas la page blanche — elle se voit
    — mais le champ qui disparaît en silence parce que son bloc a été déplacé
    dans une branche qui ne s'ouvre plus. On rend la fiche la plus remplie
    possible et on vérifie que chaque famille d'information y est encore.
    """
    from app.models import Referential, UserService
    sup = Supplier(name='Éditeur', customer_ref='CLI-42', support_phone='01 02 03',
                   support_email='support@edi.fr', commercial_contact='Jean Commercial',
                   dpo_contact='Dee Pio', dpo_email='dpo@edi.fr')
    ct = Contract(name='Marché 2026')
    db.session.add_all([sup, ct])
    db.session.commit()
    tech = Referential.query.filter_by(kind='technology').first()
    sw = Software(name='Complet', supplier_id=sup.id, hosting='saas', is_docker=True,
                  version='2.1', criticality='haute',
                  technology_id=tech.id if tech else None,
                  source_type='editeur', auth_mode='ldap', auth_strong=True,
                  users_count=120, users_max=100,
                  responsible='Rita Métier', responsible_email='rita@ville.fr',
                  tech_responsible='Théo Technique', url='https://appli.ville.fr',
                  gdpr_personal_data=True, gdpr_categories='État civil',
                  gdpr_registry_ref='REG-12', gdpr_location='ue',
                  description='Note libre', lifecycle='production')
    db.session.add(sw)
    db.session.commit()
    sw.contracts.append(ct)
    sw.user_services.append(UserService(name='Ressources humaines'))
    db.session.commit()

    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    for attendu in ('Dépassement de licence',   # alerte de tête
                    '2.1', 'Rita Métier', 'Théo Technique',   # grille dense
                    '2FA', 'Marché 2026', 'Ressources humaines',
                    'Éditeur', 'CLI-42', 'Jean Commercial',   # colonne de droite
                    'État civil', 'REG-12', 'dpo@edi.fr',     # volet RGPD
                    'Interconnexions', 'Dossiers',  # cartes du bas
                    'Mises à jour liées', 'Tâches récurrentes'):
        assert attendu in html, f'« {attendu} » a disparu de la fiche'


def test_la_fiche_sans_editeur_prend_toute_la_largeur(client):
    """Sans éditeur, la colonne de droite n'a rien à montrer : elle disparaît
    au lieu de laisser un tiers d'écran vide — le défaut qui a motivé la refonte.
    """
    sw = Software(name='Maison', internal_dev=True)
    db.session.add(sw)
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'col-lg-4' not in html
    # Plus d'onglet RGPD : les donnees personnelles se saisissent dans l'onglet
    # Details et se lisent dans la Synthese -- meme quand il n'y a rien a
    # declarer : « non » est une reponse, la rubrique absente serait un oubli.
    assert 'ong-rgpd' not in html and 'name="gdpr_personal_data"' in html
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'Aucune donnée personnelle' in synthese


def test_la_synthese_resume_les_liaisons(client):
    """Un logiciel sans éditeur mais porté par un serveur : la colonne de
    droite revient pour la carte Liaisons, le serveur avec l'icône de son type."""
    from app.models import Equipment
    e = Equipment(name='SRV-MAISON', kind='nas')
    sw = Software(name='Maison', internal_dev=True, equipments=[e])
    db.session.add_all([e, sw])
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'col-lg-4' in html
    assert 'liaisons-resume' in html
    assert '#hard-drive' in html and 'SRV-MAISON' in html


def test_l_onglet_details_porte_le_formulaire(client):
    """Deuxième onglet de la fiche : le formulaire de modification, qui
    s'envoie à la route de modification et enregistre comme elle."""
    sw = Software(name='Concerto')
    db.session.add(sw)
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert html.index('data-bs-target="#vol-detail"') < html.index('data-bs-target="#vol-details"') \
        < html.index('data-bs-target="#vol-liaisons"')
    assert f'action="/inventory/logiciels/{sw.id}/edit"' in html
    assert 'name="lifecycle"' in html
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={'name': 'Concerto', 'version': '3.2'})
    assert db.session.get(Software, sw.id).version == '3.2'


def test_les_services_se_cochent_depuis_la_fiche(client):
    """La fiche montre TOUS les services en cases, coche ceux qui s'en servent,
    et une case cochée ou décochée enregistre la liste telle quelle."""
    from app.models import UserService
    a = UserService(name='Finances / Comptabilité')
    b = UserService(name='Urbanisme')
    sw = Software(name='GED')
    db.session.add_all([a, b, sw])
    db.session.commit()
    sw.user_services = [a]
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Urbanisme' in html and f'value="{a.id}" checked' in html
    client.post(f'/inventory/logiciels/{sw.id}/services', data={'user_service_ids': [str(b.id)]},
                follow_redirects=True)
    assert [x.name for x in sw.user_services] == ['Urbanisme']
    client.post(f'/inventory/logiciels/{sw.id}/services', data={}, follow_redirects=True)
    assert sw.user_services == []


def test_les_serveurs_s_associent_et_se_retirent_depuis_la_fiche(client):
    e1 = Equipment(name='SRV-CIRIL', kind='vm')
    e2 = Equipment(name='SRV-TEST', kind='vm')
    sw = Software(name='GED', no_server=True)
    db.session.add_all([e1, e2, sw])
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Choisir un serveur' in html and f'<option value="{e1.id}">SRV-CIRIL</option>' in html
    client.post(f'/inventory/logiciels/{sw.id}/servers', data={'equipment_id': str(e1.id)},
                follow_redirects=True)
    assert [e.name for e in sw.equipments] == ['SRV-CIRIL'] and sw.no_server is False
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert '>SRV-CIRIL</a>' in html and f'<option value="{e1.id}">' not in html   # deja associe : plus propose
    client.post(f'/inventory/logiciels/{sw.id}/servers/{e1.id}/detach', follow_redirects=True)
    assert sw.equipments == []
    assert db.session.get(Equipment, e1.id) is not None                              # le serveur reste


def test_un_flux_se_lit_se_corrige_et_se_supprime_depuis_la_fiche(client):
    from app.models import SoftwareLink
    a = Software(name='Finances')
    b = Software(name='iParapheur')
    db.session.add_all([a, b])
    db.session.commit()
    client.post(f'/inventory/logiciels/{a.id}/links/add',
                data={'target_id': str(b.id), 'description': 'Flux PES'}, follow_redirects=True)
    lien = SoftwareLink.query.one()
    html = client.get(f'/inventory/logiciels/{a.id}').get_data(as_text=True)
    assert 'Interconnexions' in html and 'lucide-arrow-right' in html and '— Flux PES' in html
    # La fiche d en face le voit entrant.
    assert 'lucide-arrow-left' in client.get(f'/inventory/logiciels/{b.id}').get_data(as_text=True)
    # La description se corrige en place, et l on revient sur la fiche de depart.
    r = client.post(f'/inventory/logiciels/links/{lien.id}/edit',
                    data={'description': 'Flux PES - Bons de commande', 'from_id': str(b.id)})
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/inventory/logiciels/{b.id}#liaisons')
    assert lien.description == 'Flux PES - Bons de commande'
    client.post(f'/inventory/logiciels/links/{lien.id}/delete', data={'from_id': str(a.id)},
                follow_redirects=True)
    assert SoftwareLink.query.count() == 0


def test_la_modale_nouveau_serveur_cree_un_equipement_complet(client):
    r = client.post('/inventory/quick-create', data={
        'name': 'SRV-AFFGE', 'kind': 'physical', 'os_family': 'Windows',
        'os': 'Windows Server 2022', 'location': 'salle serveur', 'observations': 'Sauvegarde Veeam'})
    assert r.status_code == 200 and r.get_json()['ok']
    eq = Equipment.query.filter_by(name='SRV-AFFGE').one()
    assert eq.kind == 'physical' and eq.os == 'Windows Server 2022'
    assert eq.location == 'salle serveur' and eq.observations == 'Sauvegarde Veeam'
    # Sans nom de systeme, la famille en tient lieu ; sans rien, rien.
    client.post('/inventory/quick-create', data={'name': 'SRV-LNX', 'kind': 'vm', 'os_family': 'Linux'})
    assert Equipment.query.filter_by(name='SRV-LNX').one().os == 'Linux'
    client.post('/inventory/quick-create', data={'name': 'SRV-VIDE', 'kind': 'vm'})
    assert Equipment.query.filter_by(name='SRV-VIDE').one().os is None
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'qaModalServer' in html and 'Nouveau serveur' in html and 'Créer un serveur absent du parc' in html



def test_le_formulaire_n_efface_pas_les_rattachements(client):
    """Marchés, serveurs, services et mention « sans contrat » ont quitté le
    formulaire (onglets Contrats et Liaisons) : l'enregistrer ne les vide pas."""
    from app.models import Equipment, UserService
    e = Equipment(name='SRV-GARDE', kind='vm')
    sv = UserService(name='Finances')
    ct = Contract(name='Marché gardé')
    sw = Software(name='Garde', equipments=[e], user_services=[sv], contracts=[ct],
                  no_contract_note='porté par le CCAS')
    db.session.add_all([e, sv, ct, sw])
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}/edit').get_data(as_text=True)
    assert 'name="equipment_ids"' not in html and 'name="contract_ids"' not in html
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={'name': 'Garde', 'version': '2'})
    sw = db.session.get(Software, sw.id)
    assert sw.version == '2'
    assert [x.name for x in sw.equipments] == ['SRV-GARDE']
    assert [x.name for x in sw.user_services] == ['Finances']
    assert [x.name for x in sw.contracts] == ['Marché gardé']
    assert sw.no_contract_note == 'porté par le CCAS'


def test_contrat_en_cours():
    """En cours : commencé (ou sans début) et pas encore échu (ou sans échéance)."""
    from datetime import date, timedelta
    j = date.today()
    assert Contract(name='a').en_cours()
    assert Contract(name='b', start_date=j - timedelta(days=10), end_date=j + timedelta(days=10)).en_cours()
    assert Contract(name='c', end_date=j).en_cours()
    assert not Contract(name='d', end_date=j - timedelta(days=1)).en_cours()
    assert not Contract(name='e', start_date=j + timedelta(days=1)).en_cours()


def test_la_synthese_ne_resume_que_les_contrats_en_cours(client):
    """La carte Contrats de la Synthèse ne garde que les actes en cours ;
    l'onglet Contrats les montre tous."""
    from datetime import date, timedelta
    j = date.today()
    sw = Software(name='Tri')
    sw.contracts = [Contract(name='Acte courant', reference='COUR-1', end_date=j + timedelta(days=90)),
                    Contract(name='Acte échu', reference='ECHU-1', end_date=j - timedelta(days=30))]
    db.session.add(sw)
    db.session.commit()
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'COUR-1' in synthese and 'ECHU-1' not in synthese
    assert 'ECHU-1' in html.split('id="vol-contrats"', 1)[1]


def test_l_ancien_formulaire_se_choisit_dans_les_preferences(client, app):
    """Préférences > Formulaires : l'ancien formulaire (rubriques numérotées,
    rattachements compris) remplace la grille de SoftInventory, sur la page
    comme dans l'onglet Détails ; tout décocher y vide bien les listes."""
    from app.models import Equipment
    e = Equipment(name='SRV-ANCIEN', kind='vm')
    sw = Software(name='Ancien', equipments=[e])
    db.session.add_all([e, sw])
    db.session.commit()

    nouveau = client.get(f'/inventory/logiciels/{sw.id}/edit').get_data(as_text=True)
    assert 'logiciel-saisie' in nouveau and 'name="equipment_ids"' not in nouveau

    client.post('/preferences', data={'action': 'save_forms', 'software_form_legacy': 'on'})
    assert app.config['SOFTWARE_FORM_LEGACY'] is True
    for url in (f'/inventory/logiciels/{sw.id}/edit', f'/inventory/logiciels/{sw.id}',
                '/inventory/logiciels/create'):
        html = client.get(url).get_data(as_text=True)
        assert 'form-section form-section--' in html and 'name="equipment_ids"' in html, url
        assert 'logiciel-saisie' not in html, url

    # Plus aucun serveur coché : seul le marqueur vide part, la liste se vide.
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={'name': 'Ancien', 'equipment_ids': ''})
    assert db.session.get(Software, sw.id).equipments == []

    client.post('/preferences', data={'action': 'save_forms'})
    assert app.config['SOFTWARE_FORM_LEGACY'] is False
