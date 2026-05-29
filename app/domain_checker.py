"""Lecture de la date d'expiration d'un nom de domaine via RDAP.

RDAP (Registration Data Access Protocol) est le successeur standardise du WHOIS :
HTTP + JSON, donc fiable et facile a parser. rdap.org redirige vers le bon
registre (AFNIC pour .fr, etc.).
"""
from datetime import datetime, timezone

import requests as http_requests

RDAP_BOOTSTRAP = "https://rdap.org/domain/"


def _clean_domain(value):
    value = (value or '').strip().lower()
    if '://' in value:
        value = value.split('://', 1)[1]
    value = value.split('/', 1)[0]
    # garde le domaine enregistrable tel quel (sous-domaines laisses a l'appelant)
    return value


def fetch_domain_info(domain, timeout=15):
    """Retourne {'expiry_date': date|None, 'registrar': str|None}.
    Leve une exception si le domaine est introuvable ou la requete echoue."""
    name = _clean_domain(domain)
    if not name:
        raise ValueError("Domaine vide")

    resp = http_requests.get(RDAP_BOOTSTRAP + name, timeout=timeout,
                             headers={'Accept': 'application/rdap+json'})
    if resp.status_code == 404:
        raise ValueError("Domaine introuvable dans le RDAP")
    if resp.status_code != 200:
        raise ValueError(f"RDAP a repondu HTTP {resp.status_code}")
    data = resp.json()

    expiry = None
    for event in data.get('events', []):
        if event.get('eventAction') in ('expiration', 'expiry'):
            try:
                dt = datetime.fromisoformat(event['eventDate'].replace('Z', '+00:00'))
                expiry = dt.astimezone(timezone.utc).date()
            except (ValueError, KeyError):
                pass
            break

    registrar = None
    for ent in data.get('entities', []):
        roles = ent.get('roles', [])
        if 'registrar' in roles:
            registrar = _vcard_name(ent) or registrar
            break

    return {'expiry_date': expiry, 'registrar': registrar}


def _vcard_name(entity):
    """Extrait le nom (fn) d'une entite RDAP (format jCard)."""
    try:
        vcard = entity.get('vcardArray', [None, []])[1]
        for item in vcard:
            if item and item[0] == 'fn':
                return item[3]
    except (IndexError, KeyError, TypeError):
        pass
    return None
