"""Pagination simple en mémoire pour les listes (après tri par criticité)."""
from flask import request

PER_PAGE = 25


def paginate(items):
    """Retourne (page_items, page, pages, total) selon ?page=N."""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    total = len(items)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)
    start = (page - 1) * PER_PAGE
    return items[start:start + PER_PAGE], page, pages, total
