"""Recherche annuaire (AD) pour l'autocompletion des responsables.

L'AD n'est pas joignable en test : on verifie le repli propre (aucune erreur,
liste vide, drapeau `available` correct) et le controle d'acces de la route.
"""
from app.ldap_auth import search_directory, directory_search_available


def test_recherche_indisponible_sans_ldap(app):
    """LDAP desactive -> recherche indisponible et resultat vide (repli manuel)."""
    app.config['LDAP_ENABLED'] = False
    assert directory_search_available() is False
    assert search_directory('dupont') == []


def test_recherche_terme_trop_court(app):
    app.config['LDAP_ENABLED'] = True
    app.config['LDAP_SERVER'] = 'dc.example.lan'
    app.config['LDAP_BIND_USER'] = 'svc@example.lan'
    app.config['LDAP_BASE_DN'] = 'DC=example,DC=lan'
    assert search_directory('a') == []   # < 2 caracteres : pas de requete AD


def test_route_directory_search_repli(app, client):
    """La route renvoie available=False + results=[] quand l'AD est indisponible."""
    app.config['LDAP_ENABLED'] = False
    r = client.get('/api/directory/search?q=dupont')
    assert r.status_code == 200
    data = r.get_json()
    assert data['available'] is False
    assert data['results'] == []


def test_route_directory_search_exige_connexion(app):
    """Sans session : la route protegee par login_required n'expose rien (302/401)."""
    r = app.test_client().get('/api/directory/search?q=dupont')
    assert r.status_code in (301, 302, 401)
