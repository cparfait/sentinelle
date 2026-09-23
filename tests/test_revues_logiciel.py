"""La revue de droits pointe vers la fiche logiciel : lien posé à la saisie,
rapprochement par nom des revues existantes, nom qui suit le logiciel."""
from app import db, _migrate_data
from app.models import AccessReview, Software


def _logiciel(name):
    sw = Software(name=name)
    db.session.add(sw)
    db.session.commit()
    return sw


def test_une_revue_creee_depuis_le_formulaire_est_reliee(client):
    sw = _logiciel('GED Maarch')
    client.post('/reviews/create', data={'application': 'ged maarch', 'frequency_days': '365'},
                follow_redirects=True)
    r = AccessReview.query.first()
    assert r.software_id == sw.id
    assert r.application == 'GED Maarch'        # le nom prend la casse de la fiche
    html = client.get(f'/reviews/{r.id}').get_data(as_text=True)
    assert f'/inventory/logiciels/{sw.id}' in html
    # ... et la fiche logiciel la montre dans son onglet Suivi.
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Revues de droits' in html and f'/reviews/{r.id}' in html


def test_une_application_hors_inventaire_reste_sans_lien(client):
    client.post('/reviews/create', data={'application': 'AppLegacy', 'frequency_days': '365'},
                follow_redirects=True)
    r = AccessReview.query.first()
    assert r.software_id is None and r.application == 'AppLegacy'
    assert 'hors inventaire' in client.get(f'/reviews/{r.id}').get_data(as_text=True)


def test_modifier_la_revue_repose_ou_retire_le_lien(client):
    sw = _logiciel('Paie')
    r = AccessReview(application='AppLegacy')
    db.session.add(r)
    db.session.commit()
    client.post(f'/reviews/{r.id}/edit', data={'application': 'Paie', 'frequency_days': '365'},
                follow_redirects=True)
    assert r.software_id == sw.id
    client.post(f'/reviews/{r.id}/edit', data={'application': 'Autre', 'frequency_days': '365'},
                follow_redirects=True)
    assert r.software_id is None and r.application == 'Autre'


def test_renommer_le_logiciel_renomme_ses_revues(client):
    sw = _logiciel('GED Maarch')
    r = AccessReview(application='GED Maarch', software_id=sw.id)
    db.session.add(r)
    db.session.commit()
    client.post(f'/inventory/logiciels/{sw.id}/edit',
                data={'name': 'Maarch Courrier', 'hosting': 'on_premise'}, follow_redirects=True)
    db.session.refresh(r)
    assert r.application == 'Maarch Courrier'


# ── Migration des revues existantes ──

def test_la_migration_relie_les_revues_par_nom(app):
    sw = _logiciel('SIRH')
    db.session.add_all([AccessReview(application='sirh'),          # casse différente : relié
                        AccessReview(application='Inconnue')])     # rien de ce nom : sans lien
    db.session.commit()
    _migrate_data()
    liee, orpheline = AccessReview.query.order_by(AccessReview.id).all()
    assert liee.software_id == sw.id
    assert orpheline.software_id is None


def test_la_migration_ne_tranche_pas_entre_deux_homonymes(app):
    _logiciel('GLPI')
    _logiciel('GLPI')
    db.session.add(AccessReview(application='GLPI'))
    db.session.commit()
    _migrate_data()
    assert AccessReview.query.first().software_id is None


def test_la_migration_ignore_un_logiciel_a_la_corbeille(app):
    sw = _logiciel('Vieux')
    sw.is_active = False
    db.session.add(AccessReview(application='Vieux'))
    db.session.commit()
    _migrate_data()
    assert AccessReview.query.first().software_id is None


def test_la_migration_ne_touche_pas_un_lien_deja_pose(app):
    a = _logiciel('Finances BL')
    b = _logiciel('Finances Berger-Levrault')
    r = AccessReview(application='Finances Berger-Levrault', software_id=a.id)
    db.session.add(r)
    db.session.commit()
    _migrate_data()
    assert r.software_id == a.id and b.id != a.id
