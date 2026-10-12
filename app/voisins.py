"""La fiche précédente et la fiche suivante, pour feuilleter sans repasser
par la liste — comme dans SoftInventory.

L'ordre est celui des noms (sans tenir compte de la casse), puis des
identifiants : l'ordre d'un annuaire, le même quel que soit le tri ou le
filtre de la liste d'où l'on vient. Aux deux bouts, pas de voisin : on ne
boucle pas, le bout se voit. Débrayable dans Préférences (FICHE_NAVIGATION).
"""
from collections import namedtuple

from flask import current_app
from sqlalchemy import func

# Ce qu'il faut d'un voisin pour le lien et son infobulle.
Voisin = namedtuple('Voisin', 'id nom')


def voisins(modele, fiche, cle=None):
    """(précédente, suivante) de `fiche` parmi les fiches actives de `modele`,
    classées par `cle` — la colonne du nom de la fiche, `name` par défaut
    (`service_name` pour un compte, `application` pour une revue…)."""
    if not current_app.config.get('FICHE_NAVIGATION', True):
        return None, None
    colonne = modele.name if cle is None else cle
    q = modele.query.with_entities(modele.id, colonne)
    if hasattr(modele, 'is_active'):
        q = q.filter_by(is_active=True)
    lignes = q.order_by(func.lower(colonne), modele.id).all()
    ids = [i for i, _ in lignes]
    if fiche.id not in ids:
        return None, None
    i = ids.index(fiche.id)
    precedent = Voisin(*lignes[i - 1]) if i > 0 else None
    suivant = Voisin(*lignes[i + 1]) if i + 1 < len(lignes) else None
    return precedent, suivant
