"""Vocabulaire unique des statuts et des délais.

Quatre dictionnaires de libellés vivaient dans les gabarits, le PDF, le mail
de synthèse et le tableau de bord : « Critique / Attention / Proche »,
« Non vérifié / Nouveau », « En retard / À faire », « À surveiller / À
traiter ». Le même rouge se lisait différemment d'une page à l'autre.

Ici, UNE table. Les modèles renvoient une couleur (danger / warning / info /
success) ; tout ce qui l'affiche à un humain passe par ces fonctions.

Sens des couleurs, adossé aux seuils de `models.DEFAULT_THRESHOLDS` :
- danger  → Critique  : échéance dépassée ou sous le seuil critique.
- warning → Urgent    : sous le seuil d'alerte.
- info    → À prévoir : sous le seuil d'information.
- success → OK        : rien à faire.
- autre   → Non suivi : pas d'échéance, hors surveillance, inconnu.

Le fait que l'échéance soit DÉPASSÉE se lit dans le délai (« en retard de
5 j »), jamais dans le badge : un certificat à J+3 est critique sans être
expiré, et le badge ne doit pas mentir.
"""
from datetime import date, datetime

STATUS_LABELS = {
    'danger': 'Critique',
    'warning': 'Urgent',
    'info': 'À prévoir',
    'success': 'OK',
}
STATUS_LABEL_DEFAULT = 'Non suivi'

# Au pluriel, pour les compteurs (« 3 critiques », « 2 urgents »).
STATUS_LABELS_PLURAL = {
    'danger': 'critiques',
    'warning': 'urgents',
    'info': 'à prévoir',
    'success': 'OK',
}

PRIORITY_LABELS = {
    'critical': 'Critique',
    'high': 'Haute',
    'medium': 'Moyenne',
    'low': 'Basse',
}


def status_label(status, fallback=None):
    """Libellé français d'une couleur de statut."""
    if status in STATUS_LABELS:
        return STATUS_LABELS[status]
    return fallback if fallback is not None else STATUS_LABEL_DEFAULT


def status_label_plural(status):
    return STATUS_LABELS_PLURAL.get(status, STATUS_LABEL_DEFAULT.lower())


def compte(n, status):
    """« 1 critique », « 2 critiques », « 3 à prévoir », « 4 OK » : le
    compteur et son mot, accordés."""
    n = int(n or 0)
    mot = STATUS_LABELS_PLURAL.get(status, STATUS_LABEL_DEFAULT.lower())
    if n == 1 and mot.endswith('s') and mot not in ('à prévoir',):
        mot = mot[:-1]
    return f'{n} {mot}'


def priority_label(value):
    """Libellé d'une priorité ; une valeur inconnue est rendue telle quelle
    plutôt que masquée (elle vient d'une saisie, on veut la voir)."""
    if not value:
        return ''
    return PRIORITY_LABELS.get(value, str(value))


_JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
_MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
         'septembre', 'octobre', 'novembre', 'décembre']


def date_longue(d):
    """« mercredi 17 septembre 2026 », sans dépendre de la locale du serveur."""
    if d is None:
        return ''
    if isinstance(d, datetime):
        d = d.date()
    return f'{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}'


def jours(value, today=None):
    """Nombre de jours entre aujourd'hui et `value` (date, datetime ou entier
    déjà calculé). None si pas de date."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        today = today or datetime.now().date()
        return (value - today).days
    return None


def delai(value, passe='en retard de', futur='dans', today=None):
    """Un délai en français, relatif, jamais un nombre signé.

        -5   → « en retard de 5 j »
         0   → « aujourd'hui »
         1   → « demain »
        12   → « dans 12 j »
        None → ''

    `passe` se remplace selon l'objet : « expiré depuis » pour un certificat,
    « préavis dépassé de » pour un contrat. Le nombre de jours et son unité
    restent les mêmes partout.
    """
    d = jours(value, today)
    if d is None:
        return ''
    if d < 0:
        return f'{passe} {-d} j'
    if d == 0:
        return "aujourd'hui"
    if d == 1:
        return 'demain'
    return f'{futur} {d} j'
