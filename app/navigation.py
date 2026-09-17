"""Le menu, en un seul endroit.

Vingt entrées à plat sous trois titres (« Surveillance », « Gestion »,
« Administration ») ne disaient pas où chercher : « Gestion » contenait tout,
et les logiciels n'apparaissaient nulle part. Le menu se lit désormais en
quatre domaines, chacun répondant à une question :

- Aujourd'hui   : que dois-je faire ?
- Échéances     : qu'est-ce qui expire ? (comptes, certificats, domaines, contrats)
- Exploitation  : qu'est-ce qui tourne, et est-ce vérifié ? (sauvegardes, tests,
                  mises à jour, revues de droits)
- Parc          : qu'avons-nous, et qui appeler ? (matériel, logiciels, fournisseurs)

L'administration est repliée : on y va rarement.

La même structure sert au fil d'Ariane, en tête de chaque page : « Échéances ›
Certificats » dit d'où l'on vient sans qu'on ait à relire le menu.

Chaque entrée : endpoint de la page, libellé, icône Bootstrap, catégorie de
droit (`can_view`, None = toujours visible), clé du compteur de la barre
latérale (`nav_counts`, None = pas de compteur).
"""
from flask import request, url_for


def _e(endpoint, label, icon, perm=None, count=None, blueprint=None):
    return {
        'endpoint': endpoint, 'label': label, 'icon': icon, 'perm': perm,
        'count': count, 'blueprint': blueprint or endpoint.split('.')[0],
    }


DOMAINES = [
    {'key': 'aujourdhui', 'label': "Aujourd'hui", 'entries': [
        _e('dashboard.index', 'Tableau de bord', 'bi-grid-1x2'),
        _e('dashboard.agenda', 'À venir', 'bi-calendar-event'),
        _e('dashboard.trends', 'Tendances', 'bi-graph-up'),
    ]},
    {'key': 'echeances', 'label': 'Échéances', 'entries': [
        _e('accounts.list', 'Comptes', 'bi-key', 'accounts', 'accounts'),
        _e('certificates.list', 'Certificats', 'bi-award', 'certificates', 'certificates'),
        _e('domains.list', 'Domaines', 'bi-globe', 'domains', 'domains'),
        _e('contracts.list', 'Contrats', 'bi-file-earmark-text', 'contracts', 'contracts'),
    ]},
    {'key': 'exploitation', 'label': 'Exploitation', 'entries': [
        _e('backups.list', 'Sauvegardes', 'bi-cloud-arrow-up', 'backups', 'backups'),
        _e('tests.list', 'Tests', 'bi-clipboard-check', 'tests', 'tests'),
        _e('updates.list', 'Mises à jour', 'bi-arrow-up-circle', 'updates', 'updates'),
        _e('reviews.list', 'Revues de droits', 'bi-person-check', 'reviews', 'reviews'),
    ]},
    {'key': 'parc', 'label': 'Parc', 'entries': [
        _e('inventory.list', 'Matériel', 'bi-hdd-stack', 'inventory', 'inventory'),
        _e('software.list', 'Logiciels', 'bi-window-stack', 'inventory'),
        _e('suppliers.list', 'Fournisseurs', 'bi-building', 'contracts'),
    ]},
]

# Le domaine replié. `perm='alerts'` : le journal des alertes envoyées se
# consulte avec le droit « alerts », pas seulement en administrateur ;
# `admin=True` : réservé aux administrateurs.
ADMINISTRATION = {'key': 'administration', 'label': 'Administration', 'entries': [
    dict(_e('alerts.list', 'Alertes envoyées', 'bi-bell', 'alerts'), admin=False),
    dict(_e('users.list', 'Utilisateurs', 'bi-people'), admin=True),
    dict(_e('users.roles', 'Rôles & permissions', 'bi-shield-lock'), admin=True),
    dict(_e('users.audit', "Journal d'audit", 'bi-journal-text'), admin=True),
    dict(_e('users.scheduler_status', 'Tâches planifiées', 'bi-clock'), admin=True),
    dict(_e('connectors.index', 'Connecteurs', 'bi-plugin', blueprint='connectors'), admin=True),
    dict(_e('auth.preferences', 'Préférences', 'bi-sliders'), admin=True),
]}

# Pages qui n'ont pas d'entrée de menu mais appartiennent à un domaine.
_ORPHELINS = {
    'dashboard.trash': ('aujourdhui', 'Corbeille'),
    'dashboard.by_status': ('aujourdhui', 'Par état'),
    'search.search': ('aujourdhui', 'Recherche'),
    'auth.profile': ('administration', 'Mon profil'),
    'auth.two_factor': ('administration', 'Double authentification'),
    'referentials.index': ('administration', 'Référentiels'),
}

# Un même blueprint (users) porte plusieurs entrées : on distingue par
# endpoint exact, puis par préfixe (users.create → Utilisateurs).
_USERS_PREFIXES = {
    'users.roles': 'users.roles', 'users.audit': 'users.audit',
    'users.scheduler_status': 'users.scheduler_status',
}


def _tous_domaines():
    return DOMAINES + [ADMINISTRATION]


def entree_active():
    """(domaine, entrée) de la page courante, ou (domaine, None) pour une page
    orpheline, ou (None, None)."""
    ep = request.endpoint or ''
    bp = request.blueprint or ''
    if ep in _ORPHELINS:
        key, _ = _ORPHELINS[ep]
        dom = next(d for d in _tous_domaines() if d['key'] == key)
        return dom, None
    # Endpoint exact d'abord (tableau de bord, agenda, tendances, admin).
    for dom in _tous_domaines():
        for e in dom['entries']:
            if e['endpoint'] == ep:
                return dom, e
    if bp == 'users':
        for dom in _tous_domaines():
            for e in dom['entries']:
                if e['endpoint'] == 'users.list':
                    return dom, e
    for dom in _tous_domaines():
        for e in dom['entries']:
            if e['blueprint'] == bp and e['blueprint'] not in ('dashboard', 'auth'):
                return dom, e
    return None, None


def fil_ariane():
    """Le fil d'Ariane de la page courante : [(libellé, url|None), ...].

    Sur une page de liste : juste le domaine. Sur une fiche ou un formulaire :
    le domaine, puis la liste (cliquable). Le titre de la page, lui, est déjà
    en H1 : on ne le répète pas. Vide sur le tableau de bord."""
    dom, entree = entree_active()
    if not dom:
        return []
    ep = request.endpoint or ''
    if ep == 'dashboard.index':
        return []
    fil = [(dom['label'], None)]
    if entree is None:
        # Page orpheline : le domaine, puis le nom de la page.
        fil.append((_ORPHELINS.get(ep, (None, ''))[1], None))
    elif entree['endpoint'] != ep:
        try:
            fil.append((entree['label'], url_for(entree['endpoint'])))
        except Exception:
            fil.append((entree['label'], None))
    else:
        fil.append((entree['label'], None))
    return fil


def contexte():
    """Ce que base.html consomme."""
    dom, entree = entree_active()
    return {
        'nav_domaines': DOMAINES,
        'nav_administration': ADMINISTRATION,
        'nav_domaine_actif': dom['key'] if dom else None,
        'nav_endpoint_actif': entree['endpoint'] if entree else None,
        'fil_ariane': fil_ariane(),
    }
