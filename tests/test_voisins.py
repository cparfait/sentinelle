"""Précédent / suivant en tête des fiches (app/voisins.py, _fiche.html).

Deux chevrons feuillettent les fiches dans l'ordre des noms, sans repasser
par la liste. Un bout garde son chevron grisé ; une fiche seule n'en montre
aucun ; une fiche désactivée ne compte pas ; Préférences coupe le tout.
"""
from datetime import date

from app import db
from app.models import Account, AccessReview, Certificate


def _comptes():
    """Trois comptes dont l'ordre des noms ignore la casse : alfresco,
    Nextcloud, Zimbra."""
    objs = [Account(service_name=n, username='admin', rotation_days=90,
                    next_password_change=date(2030, 1, 1))
            for n in ('Zimbra', 'alfresco', 'Nextcloud')]
    db.session.add_all(objs)
    db.session.commit()
    return {o.service_name: o for o in objs}


def test_les_chevrons_suivent_l_ordre_des_noms(client):
    c = _comptes()
    html = client.get(f'/accounts/{c["Nextcloud"].id}').get_data(as_text=True)
    assert f'href="/accounts/{c["alfresco"].id}"' in html and 'Précédente : alfresco' in html
    assert f'href="/accounts/{c["Zimbra"].id}"' in html and 'Suivante : Zimbra' in html


def test_un_bout_garde_son_chevron_grise(client):
    c = _comptes()
    html = client.get(f'/accounts/{c["alfresco"].id}').get_data(as_text=True)
    assert 'Précédente :' not in html and 'Suivante : Nextcloud' in html
    assert 'btn-icon disabled' in html
    html = client.get(f'/accounts/{c["Zimbra"].id}').get_data(as_text=True)
    assert 'Précédente : Nextcloud' in html and 'Suivante :' not in html


def test_une_fiche_seule_n_a_pas_de_chevrons(client):
    seul = Account(service_name='Seul', username='admin', rotation_days=90,
                   next_password_change=date(2030, 1, 1))
    db.session.add(seul)
    db.session.commit()
    assert 'fiche-voisins' not in client.get(f'/accounts/{seul.id}').get_data(as_text=True)


def test_une_fiche_desactivee_ne_compte_pas(client):
    c = _comptes()
    c['Nextcloud'].is_active = False
    db.session.commit()
    html = client.get(f'/accounts/{c["alfresco"].id}').get_data(as_text=True)
    assert 'Suivante : Zimbra' in html and 'Nextcloud' not in html


def test_le_nom_de_la_fiche_depend_du_module(client):
    """Une revue se nomme par son application, un certificat par son service."""
    r1 = AccessReview(application='GLPI', frequency_days=365)
    r2 = AccessReview(application='SIRH', frequency_days=365)
    c1 = Certificate(kind='tls', service_name='API', domain='api.fr', expiry_date=date(2030, 1, 1))
    c2 = Certificate(kind='tls', service_name='Portail', domain='portail.fr', expiry_date=date(2030, 1, 1))
    db.session.add_all([r1, r2, c1, c2])
    db.session.commit()
    assert 'Suivante : SIRH' in client.get(f'/reviews/{r1.id}').get_data(as_text=True)
    assert 'Précédente : API' in client.get(f'/certificates/{c2.id}').get_data(as_text=True)


def test_le_feuilletage_se_coupe_dans_les_preferences(app, client):
    c = _comptes()
    app.config['FICHE_NAVIGATION'] = False
    try:
        html = client.get(f'/accounts/{c["Nextcloud"].id}').get_data(as_text=True)
        assert 'fiche-voisins' not in html
    finally:
        app.config['FICHE_NAVIGATION'] = True
