"""Le sélecteur « lignes par page » vit dans la barre de pagination commune.

Seul l'inventaire l'avait ; chaque liste paginée le porte désormais sans
rien passer à son gabarit : paginate() lit ?per_page (dix lignes par défaut)
et dépose la taille retenue pour _pagination.html. Le choix garde les filtres et revient en
page 1, et la recherche garde le choix.
"""
import re

from app import db
from app.models import Account


def _trente_comptes():
    db.session.add_all([Account(service_name=f'Service {i:02d}', username=f'u{i}')
                        for i in range(30)])
    db.session.commit()


def _selecteur(html):
    m = re.search(r'<select class="form-select pagination-perpage".*?</select>', html, re.S)
    assert m, 'pas de sélecteur de lignes par page'
    return m.group(0)


def _option_choisie(html):
    m = re.search(r'<option value="([^"]+)" selected>([^<]+)</option>', _selecteur(html))
    assert m
    return m.group(1), m.group(2)


def test_la_liste_des_comptes_porte_le_selecteur(client):
    _trente_comptes()
    html = client.get('/accounts/').get_data(as_text=True)
    assert '1–10 sur 30' in html
    url, libelle = _option_choisie(html)
    assert libelle == '10 / page'
    assert 'per_page=10' in url
    # Chaque choix est une adresse de la même liste, avec sa taille.
    assert '/accounts/?per_page=25' in _selecteur(html)
    assert 'per_page=all' in _selecteur(html)


def test_la_taille_demandee_est_appliquee(client):
    _trente_comptes()
    html = client.get('/accounts/?per_page=25').get_data(as_text=True)
    assert '1–25 sur 30' in html
    assert _option_choisie(html)[1] == '25 / page'
    vingt = client.get('/accounts/?per_page=20').get_data(as_text=True)
    assert '1–20 sur 30' in vingt and _option_choisie(vingt)[1] == '20 / page'
    quinze = client.get('/accounts/?per_page=15').get_data(as_text=True)
    assert '1–15 sur 30' in quinze and _option_choisie(quinze)[1] == '15 / page'
    tout = client.get('/accounts/?per_page=all').get_data(as_text=True)
    assert _option_choisie(tout)[1] == 'Tous'
    assert tout.count('Service ') >= 30
    # Une taille hors liste retombe sur la valeur par défaut.
    bizarre = client.get('/accounts/?per_page=7').get_data(as_text=True)
    assert '1–10 sur 30' in bizarre


def test_le_choix_garde_les_filtres_et_revient_en_page_1(client):
    _trente_comptes()
    html = client.get('/accounts/?q=Service&page=2&per_page=10').get_data(as_text=True)
    assert '11–20 sur 30' in html
    sel = _selecteur(html)
    assert 'q=Service' in sel
    assert 'page=' not in sel.replace('per_page=', '')
    # La recherche garde la taille choisie.
    assert 'name="per_page" value="10"' in html


def test_le_journal_d_audit_porte_le_selecteur(client):
    html = client.get('/users/audit').get_data(as_text=True)
    assert 'pagination-perpage' in html
    assert _option_choisie(html)[1] == '10 / page'
    vingt_cinq = client.get('/users/audit?per_page=25').get_data(as_text=True)
    assert _option_choisie(vingt_cinq)[1] == '25 / page'


def test_l_inventaire_porte_le_meme_selecteur(client):
    html = client.get('/inventory/').get_data(as_text=True)
    assert html.count('pagination-perpage') == 1
    assert _option_choisie(html)[1] == '10 / page'


def test_la_taille_choisie_est_retenue_liste_par_liste(client, app):
    """Préférences > Listes (PAGINATION_MEMORY) : l'utilisateur retrouve la
    taille qu'il a choisie sur une liste en y revenant, sans que les autres
    listes en héritent ; coupé, chaque liste repart à dix lignes."""
    from app.models import Supplier
    _trente_comptes()
    db.session.add_all([Supplier(name=f'Fournisseur {i:02d}') for i in range(30)])
    db.session.commit()

    client.get('/accounts/?per_page=25')
    html = client.get('/accounts/').get_data(as_text=True)
    assert '1–25 sur 30' in html and _option_choisie(html)[1] == '25 / page'
    assert '1–10 sur 30' in client.get('/suppliers/').get_data(as_text=True)

    client.get('/accounts/?per_page=all')
    assert _option_choisie(client.get('/accounts/').get_data(as_text=True))[1] == 'Tous'

    app.config['PAGINATION_MEMORY'] = False
    try:
        assert '1–10 sur 30' in client.get('/accounts/').get_data(as_text=True)
    finally:
        app.config['PAGINATION_MEMORY'] = True
