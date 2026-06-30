"""Helpers partages pour le parsing defensif des champs de formulaire et le tri
des listes par criticite.

Ces fonctions tolerent une saisie vide, absente ou non conforme (chaine vide,
texte non numerique...) sans lever d'exception : un POST malforme ne doit jamais
provoquer d'erreur 500 ni faire perdre la saisie a l'utilisateur.
"""
from datetime import datetime


def parse_date(value):
    """Parse une date 'YYYY-MM-DD'. Renvoie None si vide ou invalide."""
    if value:
        try:
            return datetime.strptime(value.strip(), '%Y-%m-%d').date()
        except (ValueError, AttributeError):
            pass
    return None


def parse_int(value, default=None, minimum=None):
    """Parse un entier. Renvoie `default` si vide/non numerique ; borne a
    `minimum` si fourni."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None and n < minimum:
        return minimum
    return n


def parse_float(value, default=None):
    """Parse un nombre decimal (virgule ou point acceptes). Renvoie `default`
    si vide ou invalide."""
    if value is None:
        return default
    raw = str(value).strip().replace(',', '.')
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Ordre d'affichage des listes : le plus critique en premier, le sain en dernier.
STATUS_RANK = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}


def status_rank(status):
    """Cle de tri d'un statut (danger=0 ... success=3, inconnu=4)."""
    return STATUS_RANK.get(status, 4)
