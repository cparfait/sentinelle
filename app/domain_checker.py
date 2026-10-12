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
    """Retourne {'expiry_date': date|None, 'renewed_on': date|None,
    'registrar': str|None}. `renewed_on` : le dernier renouvellement, lu dans
    l'evenement « last changed » (a defaut l'enregistrement) — le debut de la
    frise du bandeau. Leve une exception si le domaine est introuvable ou la
    requete echoue."""
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

    expiry = changed = registration = None
    for event in data.get('events', []):
        action = event.get('eventAction')
        if action not in ('expiration', 'expiry', 'last changed', 'registration'):
            continue
        try:
            dt = datetime.fromisoformat(event['eventDate'].replace('Z', '+00:00'))
            d = dt.astimezone(timezone.utc).date()
        except (ValueError, KeyError):
            continue
        if action in ('expiration', 'expiry'):
            expiry = expiry or d
        elif action == 'last changed':
            changed = d
        else:
            registration = d
    # « last changed » date aussi une simple mise a jour administrative, mais
    # c'est le plus souvent le renouvellement ; un debut posterieur a
    # l'expiration ne ferait pas une frise.
    renewed_on = changed or registration
    if renewed_on and expiry and renewed_on >= expiry:
        renewed_on = None

    registrar = None
    for ent in data.get('entities', []):
        roles = ent.get('roles', [])
        if 'registrar' in roles:
            registrar = _vcard_name(ent) or registrar
            break

    return {'expiry_date': expiry, 'renewed_on': renewed_on, 'registrar': registrar}


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
