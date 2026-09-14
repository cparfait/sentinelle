"""Services utilisateurs, flux entre logiciels, dossiers du partage réseau et
référentiels administrables."""
from app import db, _migrate_data
from app.models import (Software, SoftwareLink, SoftwareShare, UserService,
                        Referential, Certificate, TestTask)


# ── Services utilisateurs ──

def test_un_logiciel_sert_plusieurs_directions(client):
    """Et une direction utilise plusieurs logiciels : le lien va dans les deux
    sens."""
    a = UserService(name='État civil')
    b = UserService(name='Urbanisme')
    db.session.add_all([a, b])
    db.session.commit()
    client.post('/inventory/logiciels/create', data={
        'name': 'Parapheur', 'user_service_ids': [str(a.id), str(b.id)]},
        follow_redirects=True)
    sw = Software.query.filter_by(name='Parapheur').one()
    assert {s.name for s in sw.user_services} == {'État civil', 'Urbanisme'}
    assert [x.name for x in a.software] == ['Parapheur']


def test_un_service_retire_reste_sur_les_fiches(client):
    """Un service se réorganise ; l'historique de ce qu'il utilisait, non. Il
    disparaît des listes déroulantes, pas des fiches."""
    sv = UserService(name='Jeunesse')
    db.session.add(sv)
    db.session.commit()
    sw = Software(name='Portail famille')
    db.session.add(sw)
    db.session.commit()
    sw.user_services = [sv]
    db.session.commit()

    client.post(f'/referentiels/services/{sv.id}/delete', follow_redirects=True)
    db.session.expire_all()
    assert sv.is_active is False
    assert [s.name for s in sw.user_services] == ['Jeunesse']   # la fiche le garde
    assert sv not in UserService.options()                      # la liste ne l'offre plus


def test_un_service_en_double_est_refuse(client):
    db.session.add(UserService(name='Finances'))
    db.session.commit()
    r = client.post('/referentiels/services/add', data={'name': 'Finances'},
                    follow_redirects=True)
    assert 'existe' in r.get_data(as_text=True)
    assert UserService.query.filter_by(name='Finances').count() == 1


# ── Flux entre logiciels ──

def test_le_flux_est_oriente_et_se_lit_des_deux_cotes(client):
    """Savoir que la paie alimente la comptabilité, et non l'inverse, est tout
    l'intérêt de la ligne : elle ne se saisit qu'une fois."""
    paie = Software(name='Paie')
    compta = Software(name='Comptabilité')
    db.session.add_all([paie, compta])
    db.session.commit()
    client.post(f'/inventory/logiciels/{paie.id}/links/add', data={
        'target_id': str(compta.id), 'description': 'export paie mensuel'},
        follow_redirects=True)

    lien = SoftwareLink.query.one()
    assert lien.source_id == paie.id and lien.target_id == compta.id
    assert [x.target.name for x in paie.links_out] == ['Comptabilité']
    assert [x.source.name for x in compta.links_in] == ['Paie']

    # La fiche d'en face le montre comme entrant, sans qu'on l'ait saisi deux fois.
    html = client.get(f'/inventory/logiciels/{compta.id}').get_data(as_text=True)
    assert 'depuis' in html and 'Paie' in html


def test_un_logiciel_ne_s_alimente_pas_lui_meme(client):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    r = client.post(f'/inventory/logiciels/{sw.id}/links/add',
                    data={'target_id': str(sw.id)}, follow_redirects=True)
    assert 'lui-m' in r.get_data(as_text=True)
    assert SoftwareLink.query.count() == 0


def test_le_meme_flux_deux_fois_est_refuse(client):
    a = Software(name='A')
    b = Software(name='B')
    db.session.add_all([a, b])
    db.session.commit()
    for _ in range(2):
        client.post(f'/inventory/logiciels/{a.id}/links/add',
                    data={'target_id': str(b.id)}, follow_redirects=True)
    assert SoftwareLink.query.count() == 1


def test_le_flux_se_retire_depuis_les_deux_fiches(client):
    a = Software(name='A')
    b = Software(name='B')
    db.session.add_all([a, b])
    db.session.commit()
    client.post(f'/inventory/logiciels/{a.id}/links/add',
                data={'target_id': str(b.id)}, follow_redirects=True)
    lien = SoftwareLink.query.one()
    # Retiré depuis la fiche destinataire : on y revient, pas sur la source.
    r = client.post(f'/inventory/logiciels/links/{lien.id}/delete',
                    data={'from_id': str(b.id)})
    assert r.headers['Location'].endswith(f'/inventory/logiciels/{b.id}')
    assert SoftwareLink.query.count() == 0


def test_supprimer_un_logiciel_emporte_ses_flux(client):
    a = Software(name='A')
    b = Software(name='B')
    db.session.add_all([a, b])
    db.session.commit()
    db.session.add(SoftwareLink(source_id=a.id, target_id=b.id))
    db.session.commit()
    db.session.delete(a)
    db.session.commit()
    assert SoftwareLink.query.count() == 0


# ── Dossiers du partage réseau ──

def test_dossiers_du_partage(client):
    """Le chemin est affiché et copié, jamais ouvert : un navigateur refuse de
    suivre un lien file:// posé par une page servie en http(s)."""
    sw = Software(name='GLPI')
    db.session.add(sw)
    db.session.commit()
    chemin = r'\\srv-fichiers\Applications\GLPI\Installeurs'
    client.post(f'/inventory/logiciels/{sw.id}/shares/add',
                data={'label': 'Installeurs', 'path': chemin}, follow_redirects=True)
    p = SoftwareShare.query.one()
    assert p.path == chemin and p.label == 'Installeurs'

    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    # Le chemin se voit, mais aucun lien ne le pointe.
    assert 'Installeurs' in html
    assert 'file://' not in html
    assert 'js-copier' in html


def test_le_meme_dossier_deux_fois_est_refuse(client):
    sw = Software(name='GLPI')
    db.session.add(sw)
    db.session.commit()
    for _ in range(2):
        client.post(f'/inventory/logiciels/{sw.id}/shares/add',
                    data={'path': r'\\srv\part'}, follow_redirects=True)
    assert SoftwareShare.query.count() == 1


def test_un_dossier_sans_chemin_est_refuse(client):
    sw = Software(name='GLPI')
    db.session.add(sw)
    db.session.commit()
    client.post(f'/inventory/logiciels/{sw.id}/shares/add',
                data={'label': 'Installeurs'}, follow_redirects=True)
    assert SoftwareShare.query.count() == 0


# ── Tâches récurrentes rattachées à un logiciel ──

def test_une_tache_peut_porter_sur_un_logiciel(client):
    sw = Software(name='GLPI')
    db.session.add(sw)
    db.session.commit()
    client.post('/tests/create', data={
        'name': 'Mise à jour annuelle', 'test_type': 'autre',
        'software_id': str(sw.id), 'frequency_days': '365'}, follow_redirects=True)
    t = TestTask.query.filter_by(name='Mise à jour annuelle').one()
    assert t.software_id == sw.id
    # Elle apparaît sur la fiche du logiciel.
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Mise à jour annuelle' in html


def test_une_tache_sans_logiciel_reste_possible(client):
    """Une restauration de sauvegarde ou un PCA ne portent sur aucun logiciel en
    particulier."""
    client.post('/tests/create', data={
        'name': 'Test de restauration', 'test_type': 'restauration',
        'frequency_days': '90'}, follow_redirects=True)
    assert TestTask.query.filter_by(name='Test de restauration').one().software_id is None


# ── Référentiels administrables ──

def test_ajout_et_retrait_dans_une_liste(client):
    client.post('/referentiels/add', data={'kind': 'technology', 'label': 'Mainframe'},
                follow_redirects=True)
    item = Referential.query.filter_by(kind='technology', label='Mainframe').one()
    # Le doublon est refusé plutôt qu'ignoré : deux libellés identiques dans une
    # liste déroulante ne se distinguent pas.
    r = client.post('/referentiels/add', data={'kind': 'technology', 'label': 'Mainframe'},
                    follow_redirects=True)
    assert 'existe' in r.get_data(as_text=True)
    assert Referential.query.filter_by(kind='technology', label='Mainframe').count() == 1

    client.post(f'/referentiels/{item.id}/delete', follow_redirects=True)
    assert Referential.query.filter_by(label='Mainframe').count() == 0


def test_une_liste_inconnue_est_refusee(client):
    """Les valeurs dont un calcul dépend ne sont pas administrables : en ajouter
    laisserait des fiches orphelines et des filtres qui ne filtrent plus."""
    client.post('/referentiels/add', data={'kind': 'lifecycle', 'label': 'Zombie'},
                follow_redirects=True)
    assert Referential.query.filter_by(label='Zombie').count() == 0


def test_les_referentiels_sont_reserves_aux_admins(app):
    from app.models import User
    v = User(username='lecteur', email='l@v.fr', role='viewer')
    v.set_password('Lecteur-2026!')
    db.session.add(v)
    db.session.commit()
    lecteur = app.test_client()
    lecteur.post('/login', data={'username': 'lecteur', 'password': 'Lecteur-2026!'})
    r = lecteur.get('/referentiels', follow_redirects=True)
    assert 'Référentiels et services' not in r.get_data(as_text=True)
    assert Referential.query.count() > 0     # la page existe, l'accès est refusé


def test_les_services_quittent_l_ancienne_liste_de_libelles(client):
    """Ils portent un référent, avec son adresse : une liste de libellés ne
    savait pas le tenir. Les certificats qui pointaient dessus sont détachés
    plutôt que de garder un rattachement faux."""
    from sqlalchemy import text
    db.session.execute(text(
        "INSERT INTO referential (kind, label, position, is_active) "
        "VALUES ('user_service', 'Ancien service', 0, 1)"))
    db.session.commit()
    ancien = Referential.query.filter_by(kind='user_service').one()
    cert = Certificate(kind='signature', service_name='Parapheur', holder='A',
                       expiry_date=__import__('datetime').date(2030, 1, 1),
                       service_id=ancien.id)
    db.session.add(cert)
    db.session.commit()

    _migrate_data()
    db.session.expire_all()
    assert cert.service_id is None
    assert Referential.query.filter_by(kind='user_service').count() == 0
