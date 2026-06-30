"""Gestion du End-of-Life (fin de support) des OS via https://endoflife.date.

- Les donnees sont recuperees depuis l'API publique (endoflife.date/api/<produit>.json)
  et mises en cache localement (table EolCache). Le reseau n'est sollicite que
  lors d'un rafraichissement (bouton manuel ou tache planifiee), jamais au rendu.
- `lookup(os, version)` mappe l'OS libre de l'inventaire vers un produit + cycle
  et renvoie la date d'EOL et un statut (success / warning / danger).
"""
import json
import re
from datetime import datetime, timezone

import requests as http_requests
from flask import current_app

from app import db

# Mapping mot-cle (dans le champ OS, en minuscules) -> produit endoflife.date.
# Ordre important : les libelles les plus specifiques d'abord.
PRODUCT_MAP = [
    ('windows server', 'windows-server'),
    ('windows', 'windows'),
    ('ubuntu', 'ubuntu'),
    ('debian', 'debian'),
    ('rocky', 'rocky-linux'),
    ('almalinux', 'almalinux'),
    ('alma', 'almalinux'),
    ('centos', 'centos'),
    ('red hat', 'rhel'),
    ('rhel', 'rhel'),
    ('opensuse', 'opensuse'),
    ('sles', 'sles'),
    ('suse', 'sles'),
    ('fedora', 'fedora'),
    ('oracle linux', 'oracle-linux'),
]

# Tous les produits a rafraichir.
PRODUCTS = sorted({slug for _, slug in PRODUCT_MAP})

_API = 'https://endoflife.date/api/{}.json'
# Memo en process pour eviter de reparser le JSON a chaque ligne d'une liste.
_memo = {}


def _fetch_one(product, timeout=15):
    """Telecharge les cycles d'un produit et met a jour le cache. Best-effort."""
    from app.models import EolCache
    try:
        r = http_requests.get(_API.format(product), timeout=timeout,
                              headers={'Accept': 'application/json'})
        if r.status_code != 200:
            current_app.logger.warning('EOL %s : HTTP %s', product, r.status_code)
            return False
        payload = r.text
        json.loads(payload)  # validation
    except Exception as e:
        current_app.logger.warning('EOL %s : echec recuperation (%s)', product, e)
        return False
    row = db.session.get(EolCache, product)
    if row is None:
        row = EolCache(product=product)
        db.session.add(row)
    row.payload = payload
    row.fetched_at = datetime.now(timezone.utc)
    db.session.commit()
    _memo.pop(product, None)
    return True


def refresh_all():
    """Rafraichit tous les produits. Retourne (ok, total)."""
    ok = 0
    for p in PRODUCTS:
        if _fetch_one(p):
            ok += 1
    return ok, len(PRODUCTS)


def _cycles(product):
    """Cycles (liste de dicts) en cache pour un produit, ou None si absent."""
    if product in _memo:
        return _memo[product]
    from app.models import EolCache
    row = db.session.get(EolCache, product)
    data = None
    if row and row.payload:
        try:
            data = json.loads(row.payload)
        except (ValueError, TypeError):
            data = None
    _memo[product] = data
    return data


def _product_for(text):
    for kw, slug in PRODUCT_MAP:
        if kw in text:
            return slug
    return None


def _match_cycle(cycles, text):
    """Trouve le cycle dont l'identifiant apparait dans le texte (le plus long
    d'abord, avec limites de mot pour eviter les faux positifs)."""
    best = None
    for c in cycles:
        cyc = str(c.get('cycle', '')).strip()
        if not cyc:
            continue
        if re.search(r'(?<![\w.])' + re.escape(cyc) + r'(?![\w.])', text):
            if best is None or len(cyc) > len(str(best.get('cycle'))):
                best = c
    return best


def _status(eol):
    """A partir du champ 'eol' d'un cycle -> (date|None, status, days_left)."""
    # eol peut etre False (supporte), True (deja EOL) ou une date 'YYYY-MM-DD'.
    if eol is False:
        return None, 'success', None
    if eol is True:
        return None, 'danger', None
    try:
        d = datetime.strptime(str(eol), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None, None, None
    days = (d - datetime.now(timezone.utc).date()).days
    if days < 0:
        return d, 'danger', days
    if days <= 180:
        return d, 'warning', days
    return d, 'success', days


def lookup(os_str, version=None):
    """Renvoie un dict EOL pour un OS, ou None si non reconnu.
    {product, cycle, eol_date, status, days_left, has_data}"""
    text = ('%s %s' % (os_str or '', version or '')).strip().lower()
    if not text:
        return None
    product = _product_for(text)
    if not product:
        return None
    cycles = _cycles(product)
    if cycles is None:
        return {'product': product, 'cycle': None, 'eol_date': None,
                'status': None, 'days_left': None, 'has_data': False}
    cyc = _match_cycle(cycles, text)
    if not cyc:
        return {'product': product, 'cycle': None, 'eol_date': None,
                'status': None, 'days_left': None, 'has_data': True}
    eol_date, status, days = _status(cyc.get('eol'))
    return {'product': product, 'cycle': cyc.get('cycle'), 'eol_date': eol_date,
            'status': status, 'days_left': days, 'has_data': True}
