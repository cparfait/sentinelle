"""Le bureau d'enregistrement d'un domaine est relié à sa fiche fournisseur :
choix dans le formulaire ou rapprochement par nom, rattrapage des domaines
existants au démarrage, et la fiche fournisseur liste ses domaines."""
from app import db, _migrate_data
from app.models import Domain, Supplier, SUPPLIER_KIND_LABELS


def _fournisseur(name, **kw):
    s = Supplier(name=name, **kw)
    db.session.add(s)
    db.session.commit()
    return s


def test_l_annuaire_connait_le_bureau_d_enregistrement():
    assert SUPPLIER_KIND_LABELS['registrar'] == "Bureau d'enregistrement"


def test_le_texte_du_registrar_trouve_sa_fiche_par_nom_exact(client):
    ovh = _fournisseur('OVHcloud', kind='registrar')
    client.post('/domains/create', data={'name': 'mairie.fr', 'registrar': 'ovhcloud'},
                follow_redirects=True)
    d = Domain.query.first()
    assert d.registrar_id == ovh.id and d.registrar == 'ovhcloud'
    html = client.get(f'/domains/{d.id}').get_data(as_text=True)
    assert f'/suppliers/{ovh.id}' in html
    # ... et la fiche fournisseur liste le domaine.
    html = client.get(f'/suppliers/{ovh.id}').get_data(as_text=True)
    assert 'ong-domaines' in html and f'/domains/{d.id}' in html


def test_un_nom_approchant_ne_suffit_pas(client):
    _fournisseur('OVHcloud')
    client.post('/domains/create', data={'name': 'mairie.fr', 'registrar': 'OVH'},
                follow_redirects=True)
    d = Domain.query.first()
    assert d.registrar_id is None and d.registrar == 'OVH'
    assert 'sans fiche fournisseur' in client.get(f'/domains/{d.id}').get_data(as_text=True)


def test_la_fiche_choisie_prime_et_prete_son_nom(client):
    gandi = _fournisseur('Gandi')
    client.post('/domains/create', data={'name': 'mairie.fr', 'registrar_id': str(gandi.id)},
                follow_redirects=True)
    d = Domain.query.first()
    assert d.registrar_id == gandi.id and d.registrar == 'Gandi'
    # Le formulaire de modification propose la fiche, et la garde.
    html = client.get(f'/domains/{d.id}/edit').get_data(as_text=True)
    assert f'value="{gandi.id}" selected' in html
    client.post(f'/domains/{d.id}/edit', data={'name': 'mairie.fr', 'registrar': 'GANDI SAS',
                                               'registrar_id': str(gandi.id)}, follow_redirects=True)
    assert d.registrar_id == gandi.id and d.registrar == 'GANDI SAS'
    # Sans fiche choisie ni nom connu : plus de lien.
    client.post(f'/domains/{d.id}/edit', data={'name': 'mairie.fr', 'registrar': 'Inconnu'},
                follow_redirects=True)
    assert d.registrar_id is None


def test_le_formulaire_propose_l_ajout_rapide_d_un_fournisseur(client):
    html = client.get('/domains/create').get_data(as_text=True)
    assert 'name="registrar_id"' in html and 'qaModalSupplier' in html


# ── Migration des domaines existants ──

def test_la_migration_relie_par_nom_sans_homonyme(app):
    ovh = _fournisseur('OVHcloud')
    _fournisseur('Gandi')
    _fournisseur('Gandi')                         # deux homonymes : on ne tranche pas
    db.session.add_all([Domain(name='a.fr', registrar='OVHcloud'),
                        Domain(name='b.fr', registrar='Gandi'),
                        Domain(name='c.fr', registrar='OVH'),
                        Domain(name='d.fr')])
    db.session.commit()
    _migrate_data()
    a, b, c, d = Domain.query.order_by(Domain.id).all()
    assert a.registrar_id == ovh.id
    assert b.registrar_id is None and c.registrar_id is None and d.registrar_id is None


def test_la_migration_ne_touche_pas_un_lien_deja_pose(app):
    x = _fournisseur('Gandi')
    y = _fournisseur('OVHcloud')
    d = Domain(name='a.fr', registrar='OVHcloud', registrar_id=x.id)
    db.session.add(d)
    db.session.commit()
    _migrate_data()
    assert d.registrar_id == x.id and y.id != x.id
