"""Fournisseurs : onglet Détails, nouveau formulaire, nouvelle Synthèse, et
l'interrupteur « Ancien formulaire des fournisseurs » (Préférences >
Formulaires), comme pour les logiciels et les contrats."""
from app import db
from app.models import Supplier


# Tous les champs de _fill() (suppliers.py), avec les noms du formulaire.
CHAMPS = {
    'name': 'Arpège', 'kind': 'provider', 'website': 'https://arpege.fr',
    'contact_name': 'Léa', 'email': 'contact@arpege.fr', 'phone': '0102030405',
    'address': '1 rue du Port', 'postal_code': '44000', 'city': 'Nantes',
    'support_url': 'https://aide.arpege.fr', 'support_phone': '0800000000',
    'support_email': 'aide@arpege.fr', 'customer_ref': 'CLI-9',
    'hours': '8h-18h', 'hours2': 'samedi 9h-12h',
    'commercial_contact': 'DUPONT', 'commercial_phone': '0600000001', 'commercial_email': 'dupont@arpege.fr',
    'commercial2_contact': 'MOREAU', 'commercial2_phone': '0600000002', 'commercial2_email': 'moreau@arpege.fr',
    'admin_contact': 'Compta', 'admin_phone': '0600000003', 'admin_email': 'factu@arpege.fr',
    'dpo_contact': 'Martin', 'dpo_phone': '0600000004', 'dpo_email': 'dpo@arpege.fr',
    'notes': 'Escalade au N2 après 4 h.',
}


def test_le_nouveau_formulaire_porte_tous_les_champs(client):
    """Un champ absent du formulaire se lirait vide et effacerait la valeur :
    la page Modifier, l'onglet Détails et la création les portent tous."""
    sup = Supplier(name='Arpège')
    db.session.add(sup)
    db.session.commit()
    for url in (f'/suppliers/{sup.id}/edit', f'/suppliers/{sup.id}', '/suppliers/create'):
        html = client.get(url).get_data(as_text=True)
        assert 'fournisseur-saisie' in html, url
        for champ in CHAMPS:
            assert f'name="{champ}"' in html, (url, champ)
        assert 'form-section form-section--' not in html, url


def test_le_nouveau_formulaire_enregistre_et_la_synthese_relit(client):
    sup = Supplier(name='Arpège')
    db.session.add(sup)
    db.session.commit()
    client.post(f'/suppliers/{sup.id}/edit', data=CHAMPS)
    sup = db.session.get(Supplier, sup.id)
    assert sup.commercial_contact2 == 'MOREAU' and sup.dpo_email == 'dpo@arpege.fr'
    assert sup.customer_ref == 'CLI-9' and sup.hours2 == 'samedi 9h-12h'

    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'class="data-card mb-3 synthese synthese--cases"' in synthese
    assert 'MOREAU' in synthese and 'factu@arpege.fr' in synthese and 'CLI-9' in synthese
    # Les contacts vivent dans la Synthèse : plus d'onglet Contacts à part.
    assert 'id="ong-contacts"' not in html
    assert 'id="ong-details"' in html


def test_l_ancien_formulaire_des_fournisseurs_se_choisit_dans_les_preferences(client, app):
    sup = Supplier(name='Arpège', commercial_contact='DUPONT')
    db.session.add(sup)
    db.session.commit()
    client.post('/preferences', data={'action': 'save_forms', 'supplier_form_legacy': 'on'})
    assert app.config['SUPPLIER_FORM_LEGACY'] is True
    for url in (f'/suppliers/{sup.id}/edit', f'/suppliers/{sup.id}', '/suppliers/create'):
        html = client.get(url).get_data(as_text=True)
        assert 'form-section form-section--' in html, url
        assert 'fournisseur-saisie' not in html, url
    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    assert 'synthese' not in html and 'fiche-faits' in html and 'id="ong-contacts"' in html
    # L'ancien formulaire enregistre comme le nouveau.
    client.post(f'/suppliers/{sup.id}/edit', data=dict(CHAMPS, name='Arpège ancien'))
    assert db.session.get(Supplier, sup.id).name == 'Arpège ancien'
    client.post('/preferences', data={'action': 'save_forms'})
    assert app.config['SUPPLIER_FORM_LEGACY'] is False


def test_la_synthese_tait_les_contacts_vides(client):
    """Trois tirets ne disent pas qui appeler : un contact sans nom, téléphone
    ni courriel ne paraît pas ; sans aucun contact, une phrase le dit."""
    a = Supplier(name='A', dpo_email='dpo@a.fr')
    b = Supplier(name='B')
    db.session.add_all([a, b])
    db.session.commit()
    synthese = client.get(f'/suppliers/{a.id}').get_data(as_text=True).split('id="vol-details"', 1)[0]
    assert 'dpo@a.fr' in synthese and 'Commercial (second)' not in synthese
    assert 'Aucun contact renseigné.' in client.get(f'/suppliers/{b.id}').get_data(as_text=True)


def test_le_rail_de_la_synthese_ne_montre_que_ce_qu_il_a(client):
    """Contrats, Logiciels fournis, Matériels fournis : une carte par famille,
    seulement si le fournisseur en a ; sans rien, la Synthèse prend toute la
    largeur. La carte « Chez nous » (des compteurs) a disparu."""
    from app.models import Contract, Software
    seul = Supplier(name='Seul')
    editeur = Supplier(name='Éditeur')
    db.session.add_all([seul, editeur])
    db.session.commit()
    db.session.add_all([Software(name='Paie', supplier_id=editeur.id),
                        Contract(name='Maintenance Paie', supplier_id=editeur.id)])
    db.session.commit()

    html = client.get(f'/suppliers/{seul.id}').get_data(as_text=True)
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'col-lg-4' not in synthese and 'Chez nous' not in synthese

    html = client.get(f'/suppliers/{editeur.id}').get_data(as_text=True)
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'Logiciels fournis' in synthese and 'Maintenance Paie' in synthese
    assert 'Matériels fournis' not in synthese


def test_la_carte_certificats_suit_le_fournisseur_et_le_module(client, app):
    """Les certificats délivrés par le fournisseur, dans le rail, seulement
    s'il en a ; un certificat électronique disparaît avec son module."""
    from datetime import date
    from app.models import Certificate
    sup = Supplier(name='Certinomis')
    vide = Supplier(name='Sans certificat')
    db.session.add_all([sup, vide])
    db.session.commit()
    db.session.add_all([
        Certificate(kind='tls', service_name='Portail', domain='portail.fr',
                    expiry_date=date(2030, 1, 1), supplier_id=sup.id),
        Certificate(kind='signature', service_name='Mairie', holder='DUPONT',
                    expiry_date=date(2029, 1, 1), supplier_id=sup.id)])
    db.session.commit()

    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    assert 'lucide-shield-check me-2' in html and 'Portail - portail.fr' in html and 'Mairie - DUPONT' in html
    # Le menu dit aussi « Certificats » : on cherche l'icône de la carte.
    assert 'lucide-shield-check me-2' not in client.get(f'/suppliers/{vide.id}').get_data(as_text=True)

    app.config['ELECTRONIC_CERTS_ENABLED'] = False
    try:
        html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
        assert 'Portail - portail.fr' in html and 'Mairie - DUPONT' not in html
    finally:
        app.config['ELECTRONIC_CERTS_ENABLED'] = True


def test_la_carte_contrats_ne_garde_que_ceux_en_cours(client):
    """Comme sur la fiche logiciel : un acte échu n'engage plus. Il reste
    dans l'onglet Contrats, pas dans la carte de la Synthèse."""
    from datetime import date
    from app.models import Contract
    sup = Supplier(name='Éditeur')
    db.session.add(sup)
    db.session.commit()
    db.session.add_all([
        Contract(name='Acte échu', supplier_id=sup.id, end_date=date(2020, 1, 1)),
        Contract(name='Acte courant', supplier_id=sup.id, end_date=date(2099, 1, 1))])
    db.session.commit()
    html = client.get(f'/suppliers/{sup.id}').get_data(as_text=True)
    synthese = html.split('id="vol-detail"', 1)[1].split('id="vol-details"', 1)[0]
    assert 'Acte courant' in synthese and 'Acte échu' not in synthese
    onglet = html.split('id="vol-contrats"', 1)[1]
    assert 'Acte courant' in onglet and 'Acte échu' in onglet


def test_les_intitules_des_contacts_ne_reprennent_le_role_que_sans_nom(client):
    """Derrière un nom (« Commercial 1  DUPONT »), « Téléphone » suffit ; sans
    nom, l'intitulé reprend le rôle : « Courriel DPO »."""
    sup = Supplier(name='A', commercial_contact='DUPONT', commercial_phone='0100000001',
                   dpo_email='dpo@a.fr')
    db.session.add(sup)
    db.session.commit()
    synthese = client.get(f'/suppliers/{sup.id}').get_data(as_text=True).split('id="vol-details"', 1)[0]
    assert '<span class="lu-label">Téléphone</span>' in synthese
    assert 'Téléphone commercial 1' not in synthese
    assert '<span class="lu-label">Courriel DPO</span>' in synthese


def test_un_seul_commercial_perd_son_numero(client):
    """Commercial 1 et Commercial 2 ne se numérotent que s'ils sont deux."""
    seul = Supplier(name='Seul', commercial_contact2='MOREAU')
    deux = Supplier(name='Deux', commercial_contact='DUPONT', commercial_email2='b@d.fr')
    db.session.add_all([seul, deux])
    db.session.commit()
    s = client.get(f'/suppliers/{seul.id}').get_data(as_text=True).split('id="vol-details"', 1)[0]
    assert '<span class="lu-label">Commercial</span>' in s and 'Commercial 2' not in s
    d = client.get(f'/suppliers/{deux.id}').get_data(as_text=True).split('id="vol-details"', 1)[0]
    assert '<span class="lu-label">Commercial 1</span>' in d and 'Courriel commercial 2' in d
