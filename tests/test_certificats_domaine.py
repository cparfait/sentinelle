"""Le certificat TLS est relié à la fiche du domaine enregistré dont relève son
nom d'hôte : lien posé à la saisie, rattrapage à la création d'un domaine,
rapprochement des certificats existants au démarrage."""
from datetime import date

from app import db, _migrate_data
from app.models import Certificate, Domain


def _domaine(name):
    d = Domain(name=name)
    db.session.add(d)
    db.session.commit()
    return d


def test_pour_un_hote_le_domaine_le_plus_long_l_emporte(app):
    court = _domaine('collectivite.fr')
    long_ = _domaine('rh.collectivite.fr')
    _domaine('ville-collectivite.fr')
    assert Domain.for_host('www.collectivite.fr') is court
    assert Domain.for_host('intra.rh.collectivite.fr') is long_
    assert Domain.for_host('collectivite.fr') is court
    assert Domain.for_host('WWW.Collectivite.FR.') is court        # casse et point final
    # « www.ville-collectivite.fr » n'est PAS un sous-domaine de collectivite.fr
    assert Domain.for_host('www.ville-collectivite.fr').name == 'ville-collectivite.fr'
    assert Domain.for_host('www.autre.fr') is None
    assert Domain.for_host('') is None


def test_un_certificat_cree_depuis_le_formulaire_est_relie(client):
    d = _domaine('collectivite.fr')
    client.post('/certificates/create', data={'kind': 'tls', 'service_name': 'Site',
                                              'domain': 'www.collectivite.fr'},
                follow_redirects=True)
    c = Certificate.query.first()
    assert c.domain_id == d.id and c.domain == 'www.collectivite.fr'
    html = client.get(f'/certificates/{c.id}').get_data(as_text=True)
    assert f'/domains/{d.id}' in html
    # ... et la fiche domaine le liste dans son onglet Certificats.
    html = client.get(f'/domains/{d.id}').get_data(as_text=True)
    assert 'ong-certificats' in html and f'/certificates/{c.id}' in html


def test_un_hote_hors_referentiel_reste_sans_lien(client):
    _domaine('collectivite.fr')
    client.post('/certificates/create', data={'kind': 'tls', 'service_name': 'Extranet',
                                              'domain': 'extranet.prestataire.com'},
                follow_redirects=True)
    c = Certificate.query.first()
    assert c.domain_id is None
    assert 'hors du référentiel des domaines' in client.get(f'/certificates/{c.id}').get_data(as_text=True)


def test_modifier_l_hote_repose_le_lien(client):
    a = _domaine('collectivite.fr')
    b = _domaine('collectivite92.com')
    c = Certificate(kind='tls', service_name='Site', domain='www.collectivite.fr', domain_id=a.id)
    db.session.add(c)
    db.session.commit()
    client.post(f'/certificates/{c.id}/edit', data={'kind': 'tls', 'service_name': 'Site',
                                                    'domain': 'www.collectivite92.com'},
                follow_redirects=True)
    assert c.domain_id == b.id


def test_un_certificat_electronique_n_a_pas_de_domaine(client):
    _domaine('collectivite.fr')
    client.post('/certificates/create', data={'kind': 'signature', 'service_name': 'Elus',
                                              'holder': 'Durand'}, follow_redirects=True)
    assert Certificate.query.first().domain_id is None


def test_creer_le_domaine_apres_coup_ramasse_les_certificats(client):
    c = Certificate(kind='tls', service_name='Site', domain='www.collectivite.fr')
    db.session.add(c)
    db.session.commit()
    assert c.domain_id is None
    client.post('/domains/create', data={'name': 'collectivite.fr'}, follow_redirects=True)
    d = Domain.query.first()
    assert c.domain_id == d.id


# ── Migration des certificats existants ──

def test_la_migration_relie_les_certificats_par_nom_d_hote(app):
    d = _domaine('collectivite.fr')
    db.session.add_all([
        Certificate(kind='tls', service_name='Site', domain='www.collectivite.fr',
                    expiry_date=date(2027, 1, 1)),
        Certificate(kind='tls', service_name='Extranet', domain='extranet.prestataire.com'),
        Certificate(kind='signature', service_name='Elus', holder='Durand'),
    ])
    db.session.commit()
    _migrate_data()
    site, extranet, elus = Certificate.query.order_by(Certificate.id).all()
    assert site.domain_id == d.id
    assert extranet.domain_id is None and elus.domain_id is None


def test_la_migration_ne_touche_pas_un_lien_deja_pose(app):
    a = _domaine('collectivite.fr')
    b = _domaine('www.collectivite.fr')     # plus precis, mais le lien existant prime
    c = Certificate(kind='tls', service_name='Site', domain='www.collectivite.fr', domain_id=a.id)
    db.session.add(c)
    db.session.commit()
    _migrate_data()
    assert c.domain_id == a.id and b.id != a.id
