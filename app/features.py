"""Modules debrayables depuis Preferences.

Une fonctionnalite qui ne sert pas a une collectivite ne doit pas encombrer
ses ecrans : chaque module a son interrupteur, persiste par config_store
(cle dans MANAGED et _BOOL), avec un repli .env et un defaut a « actif ».
Desactive, un module disparait des ecrans et ses routes d'ecriture repondent
404 ; les donnees deja saisies restent en base et reviennent en le
reactivant.
"""
from flask import current_app, abort

# nom court -> (cle de configuration, libelle, aide)
FEATURES = {
    'quotes': ('QUOTES_ENABLED', 'Devis et consultations',
               "Mise en concurrence sur la fiche logiciel : consultations, devis reçus, devis retenu."),
    'gdpr': ('GDPR_ENABLED', 'Volet RGPD',
             "Données personnelles traitées par chaque logiciel : catégories, référence au registre, localisation."),
    'links': ('SOFTWARE_LINKS_ENABLED', 'Flux entre logiciels',
              "Interconnexions déclarées d'un logiciel à l'autre : qui alimente qui."),
    'ecerts': ('ELECTRONIC_CERTS_ENABLED', 'Certificats électroniques',
               "Certificats nominatifs (carte, clé, fichier) des élus et des agents, à côté des certificats TLS. "
               "Désactivés, ceux déjà saisis restent visibles et surveillés ; on ne peut plus en créer."),
}

CONFIG_KEYS = frozenset(k for k, _l, _h in FEATURES.values())


def enabled(name):
    """Le module est-il actif ? Defaut : oui."""
    key = FEATURES[name][0]
    return bool(current_app.config.get(key, True))


def require(name):
    """A poser en tete d'une route d'ecriture : un module coupe n'accepte
    plus rien, meme d'un formulaire garde ouvert dans un autre onglet."""
    if not enabled(name):
        abort(404)


def all_flags():
    """{nom: actif} pour les gabarits (`features.quotes`...)."""
    return {name: enabled(name) for name in FEATURES}
