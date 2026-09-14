"""Acces aux reglages applicatifs (table Setting, cle/valeur).

Pour l'instant : choix des categories prises en compte dans la « Conformite
globale » du tableau de bord. Par defaut (avant tout reglage) toutes les
categories sont comptees ; l'admin ajuste la selection dans la config.
"""
import json
from app import db
from app.models import Setting, CONFORMITY_CATEGORIES

_KEY_CONFORMITY = 'conformity_categories'
_KEY_ASSET_TYPES = 'asset_custom_types'
# Types d'actifs integres (valeur stockee, libelle). Les autres sont ajoutables
# par l'admin (leur valeur = leur libelle).
_BUILTIN_ASSET_TYPES = [('application', 'Application'), ('divers', 'Divers')]


def _load_custom_types():
    s = db.session.get(Setting, _KEY_ASSET_TYPES)
    if not s or not s.value:
        return []
    try:
        out = json.loads(s.value)
        return [t for t in out if isinstance(t, str) and t.strip()]
    except (ValueError, TypeError):
        return []


def get_asset_types():
    """Liste (valeur, libelle) des types d'actifs : integres + personnalises."""
    types = list(_BUILTIN_ASSET_TYPES)
    seen = {v for v, _ in types}
    for t in _load_custom_types():
        if t not in seen:
            types.append((t, t))
            seen.add(t)
    return types


def get_asset_type_values():
    return {v for v, _ in get_asset_types()}


def add_asset_type(label):
    """Ajoute un type personnalise (ignore si vide ou deja present)."""
    label = (label or '').strip()
    if not label or label in get_asset_type_values():
        return False
    custom = _load_custom_types()
    custom.append(label)
    s = db.session.get(Setting, _KEY_ASSET_TYPES)
    if s is None:
        s = Setting(key=_KEY_ASSET_TYPES)
        db.session.add(s)
    s.value = json.dumps(custom)
    db.session.commit()
    return True


def remove_asset_type(label):
    """Retire un type personnalise (les types integres ne sont pas supprimables)."""
    custom = _load_custom_types()
    if label not in custom:
        return False
    s = db.session.get(Setting, _KEY_ASSET_TYPES)
    s.value = json.dumps([c for c in custom if c != label])
    db.session.commit()
    return True


def get_conformity_categories():
    """Liste ordonnee des categories comptees dans la conformite globale.
    Defaut (cle absente) : toutes les categories."""
    s = db.session.get(Setting, _KEY_CONFORMITY)
    if s is None or not s.value:
        return list(CONFORMITY_CATEGORIES)
    try:
        saved = set(json.loads(s.value))
    except (ValueError, TypeError):
        return list(CONFORMITY_CATEGORIES)
    # On filtre via la liste de reference pour garder l'ordre et ignorer
    # d'eventuelles cles obsoletes.
    return [c for c in CONFORMITY_CATEGORIES if c in saved]


def set_conformity_categories(categories):
    """Enregistre la selection (liste de categories valides)."""
    chosen = set(categories or [])
    clean = [c for c in CONFORMITY_CATEGORIES if c in chosen]
    s = db.session.get(Setting, _KEY_CONFORMITY)
    if s is None:
        s = Setting(key=_KEY_CONFORMITY)
        db.session.add(s)
    s.value = json.dumps(clean)
    db.session.commit()
    return clean
