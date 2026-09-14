"""Pagination simple en mémoire pour les listes (après tri par criticité)."""
from flask import request

PER_PAGE = 25
PER_PAGE_CHOICES = (25, 50, 100, 200)


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


def paginate(items, per_page=PER_PAGE):
    """Retourne (page_items, page, pages, total) selon ?page=N.
    per_page=None => tout afficher sur une seule page."""
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
