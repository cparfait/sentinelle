"""Acces aux reglages applicatifs (table Setting, cle/valeur).

Choix des categories prises en compte dans la « Conformite globale » du
tableau de bord. Par defaut (avant tout reglage) toutes les categories sont
comptees ; l'admin ajuste la selection dans Preferences.
"""
import json
from app import db
from app.models import Setting, CONFORMITY_CATEGORIES

_KEY_CONFORMITY = 'conformity_categories'


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
