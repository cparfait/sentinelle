"""Tableau de bord personnalisable : resolution ordre/visibilite + persistance."""
import json

from app import db
from app.dashboard import (resolve_dashboard_layout, resolve_widget_spans,
                           resolve_card_order, resolve_card_layout,
                           WIDGET_SPAN_DEFAULT, DASHBOARD_WIDGETS, STAT_CARDS)
from app.models import User


ALL_KEYS = [w['key'] for w in DASHBOARD_WIDGETS]


class _FakeUser:
    """Suffisant pour resolve_dashboard_layout (lit seulement dashboard_prefs)."""
    def __init__(self, prefs=None):
        self.dashboard_prefs = prefs


def test_layout_defaut_sans_preferences():
    """Aucune preference -> tous les blocs disponibles, dans l'ordre de reference."""
    visible, hidden = resolve_dashboard_layout(_FakeUser(None), ALL_KEYS)
    assert visible == ALL_KEYS
    assert hidden == []


def test_layout_reordonne_et_masque():
    prefs = json.dumps({'order': ['stats', 'conformity'], 'hidden': ['alerts']})
    available = ['conformity', 'stats', 'alerts']
    visible, hidden = resolve_dashboard_layout(_FakeUser(prefs), available)
    assert visible == ['stats', 'conformity']   # ordre respecte
    assert hidden == ['alerts']                  # masque respecte


def test_layout_nouveau_bloc_visible_par_defaut():
    """Un bloc disponible mais absent des preferences est ajoute (visible) a la fin."""
    prefs = json.dumps({'order': ['stats'], 'hidden': ['alerts']})
    available = ['stats', 'alerts', 'attention']  # 'attention' est nouveau
    visible, hidden = resolve_dashboard_layout(_FakeUser(prefs), available)
    assert 'attention' in visible and visible[-1] == 'attention'
    assert hidden == ['alerts']


def test_layout_ignore_cles_indisponibles():
    """Une cle enregistree mais plus disponible (droit retire) est ignoree."""
    prefs = json.dumps({'order': ['alerts', 'stats'], 'hidden': ['conformity']})
    available = ['stats']  # alerts/conformity ne sont plus disponibles
    visible, hidden = resolve_dashboard_layout(_FakeUser(prefs), available)
    assert visible == ['stats']
    assert hidden == []


def test_layout_prefs_corrompues_repli_defaut():
    visible, hidden = resolve_dashboard_layout(_FakeUser('{pas du json'), ALL_KEYS)
    assert visible == ALL_KEYS and hidden == []


def test_save_layout_persiste_pour_utilisateur(app, client):
    r = client.post('/dashboard/layout', json={
        'order': ['stats', 'conformity'], 'hidden': ['alerts', 'inconnu']})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    admin = User.query.filter_by(username='admin').first()
    saved = json.loads(admin.dashboard_prefs)
    assert saved['order'] == ['stats', 'conformity']
    assert saved['hidden'] == ['alerts']  # 'inconnu' filtre (hors registre)


def test_spans_defaut_sans_preferences():
    assert resolve_widget_spans(_FakeUser(None)) == WIDGET_SPAN_DEFAULT


def test_spans_surcharge_valide_et_bornee():
    prefs = json.dumps({'spans': {
        'stats': 6,        # valide -> pris
        'attention': 99,   # hors borne max -> ignore (defaut)
        'upcoming': 1,     # hors borne min -> ignore (defaut)
        'alerts': 'x',     # non entier -> ignore
        'inconnu': 4,      # cle hors registre -> ignore
    }})
    spans = resolve_widget_spans(_FakeUser(prefs))
    assert spans['stats'] == 6
    assert spans['attention'] == WIDGET_SPAN_DEFAULT['attention']
    assert spans['upcoming'] == WIDGET_SPAN_DEFAULT['upcoming']
    assert spans['alerts'] == WIDGET_SPAN_DEFAULT['alerts']
    assert 'inconnu' not in spans


def test_save_layout_persiste_les_largeurs(app, client):
    r = client.post('/dashboard/layout', json={
        'order': ['stats'], 'hidden': [],
        'spans': {'stats': 6, 'attention': 42, 'inconnu': 8}})
    assert r.status_code == 200
    admin = User.query.filter_by(username='admin').first()
    saved = json.loads(admin.dashboard_prefs)
    assert saved['spans'] == {'stats': 6}  # 42 (hors borne) et inconnu filtres


ALL_CARDS = [c['key'] for c in STAT_CARDS]


def test_card_order_defaut_sans_preferences():
    assert resolve_card_order(_FakeUser(None), ALL_CARDS) == ALL_CARDS


def test_card_order_respecte_et_complete():
    """Ordre enregistre respecte ; vignette disponible non mentionnee -> ajoutee a la fin."""
    prefs = json.dumps({'cards': ['contracts', 'accounts']})
    available = ['accounts', 'certificates', 'contracts']
    order = resolve_card_order(_FakeUser(prefs), available)
    assert order[:2] == ['contracts', 'accounts']
    assert 'certificates' in order and order[-1] == 'certificates'


def test_card_order_ignore_indisponibles():
    prefs = json.dumps({'cards': ['inventory', 'accounts']})
    available = ['accounts']  # inventory non visible (droit)
    assert resolve_card_order(_FakeUser(prefs), available) == ['accounts']


def test_card_layout_masque_respecte():
    """Une vignette dans hidden_cards est masquee ; les autres restent visibles."""
    prefs = json.dumps({'cards': ['certificates', 'accounts'],
                        'hidden_cards': ['accounts']})
    available = ['accounts', 'certificates', 'contracts']
    visible, hidden = resolve_card_layout(_FakeUser(prefs), available)
    assert hidden == ['accounts']
    assert 'accounts' not in visible
    assert visible[0] == 'certificates'          # ordre respecte
    assert 'contracts' in visible and visible[-1] == 'contracts'  # nouvelle -> fin


def test_card_layout_masque_ignore_indisponibles():
    """Une vignette masquee mais plus disponible (droit retire) est ignoree."""
    prefs = json.dumps({'cards': ['accounts'], 'hidden_cards': ['inventory']})
    available = ['accounts']  # inventory non visible
    visible, hidden = resolve_card_layout(_FakeUser(prefs), available)
    assert visible == ['accounts'] and hidden == []


def test_save_layout_persiste_vignettes_masquees(app, client):
    r = client.post('/dashboard/layout', json={
        'order': ['stats'], 'hidden': [],
        'cards': ['accounts', 'certificates', 'inconnu'],
        'hidden_cards': ['certificates', 'inconnu']})
    assert r.status_code == 200
    admin = User.query.filter_by(username='admin').first()
    saved = json.loads(admin.dashboard_prefs)
    assert saved['hidden_cards'] == ['certificates']  # 'inconnu' filtre
    # 'certificates' masquee -> retiree de l'ordre visible (ensembles disjoints)
    assert saved['cards'] == ['accounts']


def test_save_layout_persiste_ordre_vignettes(app, client):
    r = client.post('/dashboard/layout', json={
        'order': ['stats'], 'hidden': [],
        'cards': ['contracts', 'accounts', 'inconnu']})
    assert r.status_code == 200
    admin = User.query.filter_by(username='admin').first()
    saved = json.loads(admin.dashboard_prefs)
    assert saved['cards'] == ['contracts', 'accounts']  # 'inconnu' filtre


def test_save_layout_reset(app, client):
    admin = User.query.filter_by(username='admin').first()
    admin.dashboard_prefs = json.dumps({'order': ['stats'], 'hidden': []})
    db.session.commit()
    r = client.post('/dashboard/layout', json={'reset': True})
    assert r.status_code == 200
    assert User.query.filter_by(username='admin').first().dashboard_prefs is None


def test_save_layout_desactive_globalement(app, client):
    app.config['DASHBOARD_CUSTOM'] = False
    try:
        r = client.post('/dashboard/layout', json={'order': ['stats'], 'hidden': []})
        assert r.status_code == 403
    finally:
        app.config['DASHBOARD_CUSTOM'] = True
