"""Tous les formulaires s'ouvrent, et tous portent leurs sections colorées.

Ce fichier existe pour une raison précise : `/updates/create` est resté cassé
plusieurs jours — il filtrait sur une colonne retirée avec le connecteur
SoftInventory — parce qu'aucun test n'ouvrait cet écran. Un formulaire qui ne
s'ouvre pas ne se signale nulle part ailleurs : il attend qu'on clique dessus.
"""
import re
from datetime import date

import pytest

from app import db
from app.models import (Account, Backup, Domain, AccessReview, TestTask,
                        SystemUpdate, Equipment, Software, Supplier, Contract,
                        Certificate, User)


@pytest.fixture()
def jeu(client):
    """Un exemplaire de chaque fiche, pour éprouver aussi la MODIFICATION —
    c'est là que les blocs conditionnels des gabarits se déplient."""
    objets = {
        'accounts': Account(service_name='A', username='u',
                            next_password_change=date(2030, 1, 1)),
        'backups': Backup(service_name='B'),
        'domains': Domain(name='d.fr', expiry_date=date(2030, 1, 1)),
        'reviews': AccessReview(application='R'),
        'tests': TestTask(name='T', test_type='autre'),
        'updates': SystemUpdate(name='U'),
        'inventory': Equipment(name='E', kind='network'),
        'contracts': Contract(name='C'),
        'suppliers': Supplier(name='S'),
        'certificates': Certificate(kind='signature', service_name='Cert', holder='H'),
    }
    sw = Software(name='L')
    db.session.add_all(list(objets.values()) + [sw])
    db.session.commit()
    objets['software'] = sw
    return objets


CREATIONS = [
    '/accounts/create', '/backups/create', '/domains/create', '/reviews/create',
    '/tests/create', '/updates/create', '/users/create', '/contracts/create',
    '/suppliers/create', '/inventory/create',
    '/inventory/create?famille=reseau',
    '/certificates/create?kind=tls', '/certificates/create?kind=signature',
    '/inventory/logiciels/create',
]


@pytest.mark.parametrize('url', CREATIONS)
def test_chaque_formulaire_de_creation_s_ouvre(client, jeu, url):
    r = client.get(url)
    assert r.status_code == 200, f'{url} renvoie {r.status_code}'


@pytest.mark.parametrize('url', CREATIONS)
def test_chaque_formulaire_porte_ses_sections(client, jeu, url):
    """Au moins deux sections, et pas deux fois la même couleur : une couleur
    répétée n'est plus un repère, c'est du décor."""
    html = client.get(url).get_data(as_text=True)
    sections = re.findall(r'class="form-section form-section--(\w+)', html)
    if url == '/contracts/create':
        # Le marché suit la grille de SoftInventory : pas de rubriques
        # numérotées, des cartes (Marché, Logiciels et Équipements couverts)
        # dont les titres portent les couleurs.
        sections = re.findall(r'fiche-titre fiche-titre--(\w+)', html)
    assert len(sections) >= 2, f'{url} : {len(sections)} section(s)'
    # L'ardoise est la teinte NEUTRE : elle a le droit de revenir (liste de
    # serveurs, notes). Les couleurs d'accent, non.
    accents = [c for c in sections if c != 'slate']
    assert len(accents) == len(set(accents)), f'{url} : couleur répétée {accents}'


def test_chaque_formulaire_de_modification_s_ouvre(client, jeu):
    """La modification déplie des blocs que la création laisse fermés."""
    bases = {'accounts': '/accounts', 'backups': '/backups', 'domains': '/domains',
             'reviews': '/reviews', 'tests': '/tests', 'updates': '/updates',
             'inventory': '/inventory', 'contracts': '/contracts',
             'suppliers': '/suppliers', 'certificates': '/certificates',
             'software': '/inventory/logiciels'}
    for cle, base in bases.items():
        r = client.get(f'{base}/{jeu[cle].id}/edit')
        assert r.status_code == 200, f'{base} renvoie {r.status_code}'
    admin = User.query.filter_by(username='admin').first()
    assert client.get(f'/users/{admin.id}/edit').status_code == 200


def test_les_sections_ferment_ce_qu_elles_ouvrent(client, jeu):
    """Une section mal fermée disloque la grille sans lever d'erreur : le
    gabarit rend, et la page est de travers. On compte les balises."""
    for url in CREATIONS:
        html = client.get(url).get_data(as_text=True)
        ouvertes = html.count('<fieldset class="form-section')
        fermees = html.count('</fieldset>')
        assert ouvertes == fermees, f'{url} : {ouvertes} ouvertes / {fermees} fermées'


def test_l_ecran_des_mises_a_jour_liste_les_logiciels(client, jeu):
    """La régression exacte qui avait cassé cet écran : un filtre sur une
    colonne retirée avec le connecteur SoftInventory."""
    html = client.get('/updates/create').get_data(as_text=True)
    assert 'L' in html          # le logiciel du jeu d'essai
    from app.updates import _active_assets
    noms = [a.name for a in _active_assets()]
    assert 'L' in noms and 'E' in noms
