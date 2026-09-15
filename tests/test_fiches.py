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
