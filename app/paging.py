"""Pagination simple en mémoire pour les listes (après tri par criticité)."""
import json

from flask import g, request

# Dix lignes par defaut sur toutes les listes, le selecteur sous le tableau
# permettant de voir plus large (Dom 2026-09-25).
PER_PAGE = 10
PER_PAGE_CHOICES = (10, 15, 20, 25, 50, 100, 200)


def _lire(raw):
    """Une taille telle qu'ecrite : un entier autorise, 'all' (=> None, tout
    afficher), ou False quand elle n'est pas reconnue."""
    raw = (str(raw) if raw is not None else '').strip().lower()
    if raw in ('all', 'tous'):
        return None
    try:
        v = int(raw)
        if v in PER_PAGE_CHOICES:
            return v
    except (TypeError, ValueError):
        pass
    return False


def _memoire_active():
    """La taille se retient-elle pour l'utilisateur connecte ? (Preferences >
    Listes, PAGINATION_MEMORY.)"""
    from flask import current_app
    from flask_login import current_user
    return bool(current_app.config.get('PAGINATION_MEMORY', True)
                and getattr(current_user, 'is_authenticated', False))


def _prefs(user):
    try:
        return json.loads(user.list_prefs) if user.list_prefs else {}
    except (TypeError, ValueError):
        return {}


def resolve_per_page(default=PER_PAGE):
    """La taille de page : ?per_page s'il est donne (un entier autorise, ou
    'all' => None, tout afficher) ; sinon celle que l'utilisateur a choisie la
    derniere fois sur CETTE liste ; sinon `default`.

    Retenue liste par liste, et non une taille pour toutes : « Tous » sur sept
    fournisseurs ne doit pas deplier deux cents comptes. La liste se reconnait
    a son endpoint ; un choix explicite (le selecteur) l'enregistre."""
    from flask_login import current_user
    cle = request.endpoint or ''
    demande = request.args.get('per_page')
    if demande is not None:
        v = _lire(demande)
        if v is False:
            return default
        if _memoire_active() and cle:
            prefs = _prefs(current_user)
            valeur = 'all' if v is None else v
            if prefs.get(cle) != valeur:
                prefs[cle] = valeur
                current_user.list_prefs = json.dumps(prefs)
                from app import db
                db.session.commit()
        return v
    if _memoire_active() and cle:
        retenue = _prefs(current_user).get(cle)
        if retenue is not None:
            v = _lire(retenue)
            if v is not False:
                return v
    return default


def text_search(items, q, fields):
    """Filtre une liste d'objets : garde ceux dont l'un des champs contient q."""
    if not q:
        return items
    ql = q.strip().lower()
    out = []
    for it in items:
        for f in fields:
            v = getattr(it, f, None)
            if v and ql in str(v).lower():
                out.append(it)
                break
    return out


# Valeur par defaut de paginate() : « lis ?per_page, sinon PER_PAGE ». Un
# objet a part, parce que None veut deja dire « tout afficher ».
AUTO = object()


def paginate(items, per_page=AUTO):
    """Retourne (page_items, page, pages, total) selon ?page=N.
    per_page=None => tout afficher sur une seule page ; par defaut, la taille
    vient de ?per_page (voir resolve_per_page), et chaque liste porte ainsi
    le selecteur « lignes par page » sans rien passer a son gabarit :
    la taille retenue est deposee dans g pour _pagination.html."""
    if per_page is AUTO:
        per_page = resolve_per_page()
    g.per_page = per_page
    g.per_page_choices = PER_PAGE_CHOICES
    total = len(items)
    if per_page in (None, 0):
        return items, 1, 1, total
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages, total
