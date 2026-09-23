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
latérale (`nav_counts`, None = pas de compteur), et l'icône Lucide que le menu
affiche — celles de SoftInventory, au trait fin. Le sprite qui les porte est
app/static/vendor/lucide.svg (voir tools/build_lucide_sprite.py) ; l'icône
Bootstrap reste pour les autres usages.
"""
from flask import request, url_for


def _e(endpoint, label, icon, perm=None, count=None, blueprint=None, lucide=None):
    return {
        'endpoint': endpoint, 'label': label, 'icon': icon, 'perm': perm,
        'count': count, 'blueprint': blueprint or endpoint.split('.')[0],
        'lucide': lucide,
    }


DOMAINES = [
    {'key': 'aujourdhui', 'label': "Aujourd'hui", 'entries': [
        _e('dashboard.index', 'Tableau de bord', 'bi-grid-1x2', lucide='layout-dashboard'),
        _e('dashboard.agenda', 'À venir', 'bi-calendar-event', lucide='calendar-days'),
        _e('dashboard.trends', 'Tendances', 'bi-graph-up', lucide='chart-column'),
    ]},
    {'key': 'echeances', 'label': 'Échéances', 'entries': [
        _e('accounts.list', 'Comptes', 'bi-key', 'accounts', 'accounts', lucide='key-round'),
        _e('certificates.list', 'Certificats', 'bi-award', 'certificates', 'certificates', lucide='shield-check'),
        _e('domains.list', 'Domaines', 'bi-globe', 'domains', 'domains', lucide='globe'),
        _e('contracts.list', 'Contrats', 'bi-file-earmark-text', 'contracts', 'contracts', lucide='file-pen'),
    ]},
    {'key': 'exploitation', 'label': 'Exploitation', 'entries': [
        _e('backups.list', 'Sauvegardes', 'bi-cloud-arrow-up', 'backups', 'backups', lucide='cloud-upload'),
        _e('tests.list', 'Tests', 'bi-clipboard-check', 'tests', 'tests', lucide='clipboard-list'),
        _e('updates.list', 'Mises à jour', 'bi-arrow-up-circle', 'updates', 'updates', lucide='circle-arrow-up'),
        _e('reviews.list', 'Revues de droits', 'bi-person-check', 'reviews', 'reviews', lucide='user-check'),
    ]},
    {'key': 'parc', 'label': 'Parc', 'entries': [
        _e('inventory.list', 'Matériel', 'bi-hdd-stack', 'inventory', 'inventory', lucide='server'),
        _e('software.list', 'Logiciels', 'bi-window-stack', 'inventory', 'software', lucide='package'),
        _e('suppliers.list', 'Fournisseurs', 'bi-building', 'contracts', lucide='building'),
    ]},
]

# Le domaine replié. `perm='alerts'` : le journal des alertes envoyées se
# consulte avec le droit « alerts », pas seulement en administrateur ;
# `admin=True` : réservé aux administrateurs.
ADMINISTRATION = {'key': 'administration', 'label': 'Administration', 'entries': [
    dict(_e('alerts.list', 'Alertes envoyées', 'bi-bell', 'alerts', lucide='bell'), admin=False),
    dict(_e('users.list', 'Utilisateurs', 'bi-people', lucide='users'), admin=True),
    dict(_e('users.roles', 'Rôles & permissions', 'bi-shield-lock', lucide='shield'), admin=True),
    dict(_e('users.audit', "Journal d'audit", 'bi-journal-text', lucide='notebook-text'), admin=True),
    dict(_e('users.scheduler_status', 'Tâches planifiées', 'bi-clock', lucide='calendar-clock'), admin=True),
    dict(_e('connectors.index', 'Connecteurs', 'bi-plugin', blueprint='connectors', lucide='plug'), admin=True),
    dict(_e('auth.preferences', 'Préférences', 'bi-sliders', lucide='sliders-horizontal'), admin=True),
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


# Icone Bootstrap -> icone Lucide, pour tout ce qui represente un module hors
# du menu (vignettes du tableau de bord, agenda, recherche...) : la meme icone
# partout, definie une seule fois ci-dessus.
LUCIDE_PAR_ICONE = {e['icon']: e['lucide']
                    for d in DOMAINES + [ADMINISTRATION] for e in d['entries'] if e.get('lucide')}
LUCIDE_PAR_ICONE['bi-trash3'] = 'trash-2'   # la Corbeille, hors DOMAINES


# Les icones des RUBRIQUES de fiche (« Le certificat », « Suivi », « Notes »…),
# avec la couleur de leur pastille. Une meme icone garde la meme couleur d'une
# fiche a l'autre : la cle est toujours orange, le calendrier toujours ambre.
# Les familles suivent celles du menu : orange pour ce qui expire ou se paie,
# vert pour ce qui tourne, bleu pour le materiel, violet pour les personnes et
# les liaisons, indigo pour l'ecrit, ardoise pour le reglage.
RUBRIQUES = {
    # ecrit, description
    'bi-journal-text': ('notebook-text', 'indigo'),
    'bi-file-earmark-text': ('file-pen', 'orange'),
    'bi-paperclip': ('paperclip', 'indigo'),
    'bi-folder2-open': ('folder-open', 'indigo'),
    'bi-info-circle': ('info', 'sky'),
    'bi-flag': ('flag', 'rose'),
    'bi-tag': ('tag', 'indigo'),
    'bi-tags': ('tags', 'indigo'),
    # acces, securite
    'bi-key': ('key-round', 'orange'),
    'bi-shield-lock': ('lock-keyhole', 'orange'),
    'bi-shield-check': ('shield-check', 'orange'),
    'bi-patch-check': ('badge-check', 'orange'),
    'bi-award': ('shield-check', 'orange'),
    'bi-person-lock': ('user-lock', 'orange'),
    # personnes
    'bi-person': ('user', 'violet'),
    'bi-people': ('users', 'violet'),
    'bi-person-badge': ('id-card', 'violet'),
    'bi-person-check': ('user-check', 'violet'),
    'bi-person-gear': ('user-cog', 'violet'),
    'bi-person-lines-fill': ('contact-round', 'violet'),
    'bi-building': ('building', 'violet'),
    # liaisons
    'bi-diagram-3': ('network', 'violet'),
    'bi-diagram-2': ('git-fork', 'violet'),
    # temps
    'bi-calendar-event': ('calendar-days', 'amber'),
    'bi-calendar-check': ('calendar-check', 'amber'),
    'bi-calendar-range': ('calendar-range', 'amber'),
    'bi-arrow-repeat': ('refresh-cw', 'amber'),
    'bi-arrow-up-circle': ('circle-arrow-up', 'emerald'),
    # argent
    'bi-cash-coin': ('coins', 'orange'),
    'bi-receipt': ('receipt', 'orange'),
    # materiel, exploitation
    'bi-hdd-stack': ('server', 'sky'),
    'bi-hdd-network': ('hard-drive', 'sky'),
    'bi-hdd': ('hard-drive', 'sky'),
    'bi-pc-display': ('monitor', 'sky'),
    'bi-cpu': ('cpu', 'sky'),
    'bi-window-stack': ('package', 'sky'),
    'bi-globe': ('globe', 'sky'),
    'bi-cloud': ('cloud', 'emerald'),
    'bi-cloud-arrow-up': ('cloud-upload', 'emerald'),
    'bi-clipboard-check': ('clipboard-list', 'emerald'),
    'bi-life-preserver': ('life-buoy', 'emerald'),
    # reglage
    'bi-tools': ('wrench', 'slate'),
    'bi-sliders': ('sliders-horizontal', 'slate'),
    'bi-gear-wide-connected': ('settings', 'slate'),
}


def _bi(icone):
    if not icone:
        return None
    return icone if icone.startswith('bi-') else 'bi-' + icone


def lucide_de(icone):
    """Le nom Lucide d'une icone Bootstrap (« bi-key » ou « key »), ou None
    si rien n'y correspond : le gabarit retombe alors sur Bootstrap. Le menu
    a la priorite sur les rubriques, pour qu'un module garde son icone."""
    icone = _bi(icone)
    if not icone:
        return None
    if icone in LUCIDE_PAR_ICONE:
        return LUCIDE_PAR_ICONE[icone]
    rubrique = RUBRIQUES.get(icone)
    return rubrique[0] if rubrique else None


def couleur_icone(icone):
    """La couleur de pastille d'une icone de rubrique (« orange », « sky »…),
    ou « slate » quand l'icone n'a pas de famille."""
    rubrique = RUBRIQUES.get(_bi(icone) or '')
    return rubrique[1] if rubrique else 'slate'


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
