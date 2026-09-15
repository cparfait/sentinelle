"""Toutes les fiches se lisent de la meme facon.

Les fiches ont longtemps eu trois mises en page selon l'ecran : des tableaux ou
l'intitule prenait 45 % de la largeur, des colonnes Bootstrap a demi vides, et
aucun decoupage visible. La meme information changeait de forme d'un ecran a
l'autre, et le decoupage appris en saisissant ne servait a rien en relisant.

Ce fichier verrouille les trois regles communes : la grille dense, les sections
en blocs colores, et des balises qui se ferment.
"""
from datetime import date

import pytest

from app import db
from app.models import (Account, Backup, Domain, AccessReview, TestTask,
                        SystemUpdate, Equipment, Software, Supplier, Contract,
                        Certificate)


@pytest.fixture()
def jeu(client):
    """Une fiche de chaque sorte, remplie : c'est REMPLIE qu'une fiche deplie
    ses blocs conditionnels, donc qu'elle expose ses defauts."""
    sup = Supplier(name='Éditeur', support_phone='01 02 03 04 05',
                   customer_ref='CLI-42', hours='9h-18h')
    eq = Equipment(name='SRV-APP01', kind='vm', ip_address='10.0.0.1')
    db.session.add_all([sup, eq])
    db.session.commit()
    objets = {
        '/accounts': Account(service_name='Firewall', username='admin',
                             url='https://fw.local', priority='high',
                             rotation_days=90, description='Compte de secours',
                             last_password_change=date(2026, 1, 1),
                             next_password_change=date(2030, 1, 1)),
        '/backups': Backup(service_name='Veeam', backup_type='full',
                           location='NAS', frequency='daily'),
        '/domains': Domain(name='exemple.fr', registrar='OVH',
                           expiry_date=date(2030, 1, 1)),
        '/reviews': AccessReview(application='SIRH', responsible='Rita',
                                 responsible_email='rita@ville.fr',
                                 frequency_days=180),
        '/tests': TestTask(name='Test de restauration', test_type='restauration',
                           frequency_days=90, priority='high'),
        '/updates': SystemUpdate(name='Serveur web', current_version='1.0',
                                 latest_version='1.2', equipment_id=eq.id),
        '/inventory': eq,
        '/contracts': Contract(name='Marché 2026', supplier_id=sup.id,
                               cost_yearly=1200, end_date=date(2030, 1, 1)),
        '/suppliers': sup,
        '/certificates': Certificate(kind='tls', service_name='Portail',
                                     domain='portail.fr', issuer='Sectigo',
                                     expiry_date=date(2030, 1, 1)),
    }
    sw = Software(name='SIRH', supplier_id=sup.id, hosting='saas', version='3.1')
    db.session.add_all([o for o in objets.values() if o.id is None] + [sw])
    db.session.commit()
    objets['/inventory/logiciels'] = sw
    return objets


def _fiches(jeu):
    return [(f'{base}/{obj.id}', base) for base, obj in jeu.items()]


def test_chaque_fiche_s_ouvre(client, jeu):
    for url, _ in _fiches(jeu):
        assert client.get(url).status_code == 200, url


def test_aucune_fiche_ne_delaye_ses_champs(client, jeu):
    """Le tableau a deux colonnes, dont l'intitule occupait 45 % de la largeur,
    tirait un vide de plusieurs centimetres entre le libelle et sa valeur."""
    for url, _ in _fiches(jeu):
        html = client.get(url).get_data(as_text=True)
        assert 'fiche-grille' in html, f'{url} : pas de grille dense'
        assert 'table-borderless' not in html, f'{url} : un tableau de champs a survecu'


def test_chaque_fiche_montre_ses_sections(client, jeu):
    """Un lisere seul ne decoupe rien : sur une fiche de trente champs, l'oeil
    n'y voit qu'une suite d'intitules. Il faut le bandeau et la bordure."""
    import re
    for url, _ in _fiches(jeu):
        html = client.get(url).get_data(as_text=True)
        blocs = re.findall(r'fiche-bloc fiche-bloc--(\w+)', html)
        assert len(blocs) >= 2, f'{url} : {len(blocs)} bloc(s) colore(s)'


def test_les_balises_se_ferment(client, jeu):
    """Une grille mal fermee disloque la page sans lever d'erreur : le gabarit
    rend, et l'ecran est de travers."""
    for url, _ in _fiches(jeu):
        html = client.get(url).get_data(as_text=True)
        assert html.count('<div') == html.count('</div>'), url


def test_chaque_fiche_repond_avant_d_etre_lue(client, jeu):
    """Le bandeau de faits porte ce qu'on vient verifier neuf fois sur dix.

    Six cases au plus : au-dela ce n'est plus un resume, c'est un tableau, et il
    faudrait de nouveau le lire — ce qui etait precisement le defaut d'avant.
    """
    import re
    for url, _ in _fiches(jeu):
        html = client.get(url).get_data(as_text=True)
        assert 'fiche-faits' in html, f'{url} : pas de bandeau de faits'
        cases = len(re.findall(r'class="fiche-fait"', html))
        assert 3 <= cases <= 6, f'{url} : {cases} case(s) dans le bandeau'


def test_la_valeur_se_pose_en_face_de_son_intitule(client, jeu):
    """L'intitule etait AU-DESSUS de sa valeur : chaque champ pesait deux lignes,
    les blocs doublaient de hauteur et la fiche defilait. Les deux sont
    desormais sur la meme ligne — sauf les listes, que l'alignement a droite
    hacherait."""
    html = client.get(f"/inventory/logiciels/{jeu['/inventory/logiciels'].id}").get_data(as_text=True)
    assert 'fiche-champ' in html
    # Le gabarit ne doit plus produire de bloc colore : la couleur est passee au
    # filet du titre, et huit fonds colores se neutralisaient l'un l'autre.
    assert 'form-section' not in html


def test_les_pieces_jointes_sont_a_un_clic(client, jeu):
    """Elles vivaient a deux ecrans du haut de la fiche, et rien n'annoncait
    leur existence depuis le premier. L'onglet les remonte ET affiche leur
    nombre : « Documents 3 » se lit sans descendre."""
    sw = jeu['/inventory/logiciels']
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'fiche-onglets' in html
    assert 'data-bs-target="#vol-documents"' in html
    assert 'data-bs-target="#vol-detail"' in html
    # Le volet existe dans la page : l'onglet ne renvoie pas vers une autre URL,
    # il devoile ce qui est deja rendu — pas de second aller-retour serveur.
    assert 'id="vol-documents"' in html
