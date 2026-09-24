"""Modules débrayables depuis Préférences : devis, RGPD, flux entre logiciels,
certificats électroniques. Coupé, un module disparaît des écrans et ses
routes d'écriture répondent 404 ; les données restent."""
from app import db
from app.models import Software, Consultation, Quote, Certificate


def _logiciel(**kw):
    sw = Software(name='GED', **kw)
    db.session.add(sw)
    db.session.commit()
    return sw


# ── Préférences ──

def test_les_quatre_modules_se_reglent_depuis_les_preferences(client, app):
    html = client.get('/preferences').get_data(as_text=True)
    for name in ('quotes', 'gdpr', 'links', 'ecerts'):
        assert f'name="module_{name}"' in html
    assert 'Tous les modules actifs' in html
    # Tout décocher : les quatre clés passent à faux et sont persistées.
    client.post('/preferences', data={'action': 'save_modules'}, follow_redirects=True)
    for key in ('QUOTES_ENABLED', 'GDPR_ENABLED', 'SOFTWARE_LINKS_ENABLED', 'ELECTRONIC_CERTS_ENABLED'):
        assert app.config[key] is False
    from app import config_store
    config_store.load(app)
    assert app.config['GDPR_ENABLED'] is False
    assert '4 modules désactivés' in client.get('/preferences').get_data(as_text=True)
    # Un seul recoché.
    client.post('/preferences', data={'action': 'save_modules', 'module_gdpr': 'on'},
                follow_redirects=True)
    assert app.config['GDPR_ENABLED'] is True and app.config['QUOTES_ENABLED'] is False


# ── Devis ──

def test_devis_coupes_plus_d_onglet_ni_de_route_ni_de_recherche(client, app):
    sw = _logiciel()
    cons = Consultation(software_id=sw.id, subject='Renouvellement')
    db.session.add(cons)
    db.session.commit()
    db.session.add(Quote(consultation_id=cons.id, supplier_name='Docuware'))
    db.session.commit()
    assert 'Devis' in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'Docuware' in client.get('/search?q=docuware').get_data(as_text=True)

    app.config['QUOTES_ENABLED'] = False
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'ong-devis' not in html and 'Renouvellement' not in html
    assert 'Docuware' not in client.get('/search?q=docuware').get_data(as_text=True)
    r = client.post(f'/contracts/consultations/{sw.id}/add', data={'subject': 'Autre'})
    assert r.status_code == 404
    assert client.post(f'/contracts/quotes/{cons.quotes.first().id}/delete').status_code == 404
    # Les données sont toujours là.
    assert Quote.query.count() == 1


# ── RGPD ──

def test_rgpd_coupe_le_formulaire_n_efface_pas_ce_qui_etait_saisi(client, app):
    sw = _logiciel(gdpr_personal_data=True, gdpr_categories='état civil',
                   gdpr_registry_ref='T-12', gdpr_location='ue')
    app.config['GDPR_ENABLED'] = False
    html = client.get(f'/inventory/logiciels/{sw.id}/edit').get_data(as_text=True)
    assert 'gdpr_personal_data' not in html
    assert 'ong-rgpd' not in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={'name': 'GED', 'hosting': 'saas'},
                follow_redirects=True)
    db.session.refresh(sw)
    assert sw.gdpr_personal_data is True and sw.gdpr_categories == 'état civil'
    assert sw.gdpr_registry_ref == 'T-12' and sw.gdpr_location == 'ue'
    # Réactivé, le formulaire reprend la main.
    app.config['GDPR_ENABLED'] = True
    client.post(f'/inventory/logiciels/{sw.id}/edit', data={'name': 'GED', 'hosting': 'saas'},
                follow_redirects=True)
    db.session.refresh(sw)
    assert sw.gdpr_personal_data is False


# ── Flux entre logiciels ──

def test_flux_coupes_plus_de_bloc_ni_de_route(client, app):
    sw = _logiciel()
    autre = Software(name='Paie')
    db.session.add(autre)
    db.session.commit()
    assert 'Interconnexions' in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    app.config['SOFTWARE_LINKS_ENABLED'] = False
    assert 'Interconnexions' not in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    r = client.post(f'/inventory/logiciels/{sw.id}/links/add', data={'target_id': str(autre.id)})
    assert r.status_code == 404


# ── Certificats électroniques ──

def test_certificats_electroniques_coupes_creation_refusee_existants_visibles(client, app):
    c = Certificate(kind='signature', service_name='Parapheur', holder='Durand')
    db.session.add(c)
    db.session.commit()
    app.config['ELECTRONIC_CERTS_ENABLED'] = False
    html = client.get('/certificates/').get_data(as_text=True)
    assert 'kind=signature' not in html.split('seg-tab')[0]     # plus d'entrée « créer »
    assert 'Durand' in html                                        # l'existant reste listé
    r = client.get('/certificates/create?kind=signature')
    assert r.status_code == 302 and r.headers['Location'].endswith('/certificates/')
    r = client.post('/certificates/create', data={'kind': 'signature', 'service_name': 'X',
                                                  'holder': 'Y'})
    assert r.status_code == 302
    assert Certificate.query.filter_by(service_name='X').first() is None
    # Le formulaire TLS ne propose plus la bascule.
    assert 'certificat électronique ?' not in client.get('/certificates/create').get_data(as_text=True)
