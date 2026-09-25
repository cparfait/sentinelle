"""Pagination simple en mémoire pour les listes (après tri par criticité)."""
from flask import g, request

# Dix lignes par defaut sur toutes les listes, le selecteur sous le tableau
# permettant de voir plus large (Dom 2026-09-25).
PER_PAGE = 10
PER_PAGE_CHOICES = (10, 25, 50, 100, 200)


def resolve_per_page(default=PER_PAGE):
    """Lit ?per_page : un entier autorise, ou 'all' (=> None, tout afficher)."""
    raw = (request.args.get('per_page') or '').strip().lower()
    if raw in ('all', 'tous'):
        return None
    try:
        v = int(raw)
        if v in PER_PAGE_CHOICES:
            return v
    except (TypeError, ValueError):
        pass
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
