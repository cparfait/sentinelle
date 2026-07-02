"""Interrogation des journaux de Certificate Transparency via crt.sh.

Decouvre les certificats emis pour un domaine et ses sous-domaines, y compris
ceux inconnus de la DSI. Best-effort : crt.sh est parfois lent ou instable ;
l'appelant doit gerer les exceptions.
"""
from datetime import datetime, timezone

import requests as http_requests

CRTSH_URL = "https://crt.sh/"


def _clean_domain(value):
    value = (value or '').strip().lower()
    if '://' in value:
        value = value.split('://', 1)[1]
    value = value.split('/', 1)[0]
    value = value.split(':', 1)[0]
    return value.lstrip('*').lstrip('.')


def _parse_dt(value):
    """crt.sh renvoie des dates ISO sans fuseau (ex. '2024-01-02T03:04:05') :
    on les considere en UTC."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '')).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_date(value):
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _normalize(row):
    try:
        cid = int(row.get('id'))
    except (TypeError, ValueError, AttributeError):
        return None
    return {
        'crtsh_id': cid,
        'serial_number': (row.get('serial_number') or '')[:128] or None,
        'common_name': (row.get('common_name') or '')[:256] or None,
        'name_value': row.get('name_value') or '',
        'issuer_name': (row.get('issuer_name') or '')[:256] or None,
        'not_before': _parse_date(row.get('not_before')),
        'not_after': _parse_date(row.get('not_after')),
        'entry_timestamp': _parse_dt(row.get('entry_timestamp')),
    }


def fetch_ct_certificates(domain, timeout=25):
    """Retourne la liste (triee par id croissant) des certificats connus de
    crt.sh pour le domaine et ses sous-domaines. Chaque element est un dict
    normalise. Leve une exception si la requete echoue."""
    name = _clean_domain(domain)
    if not name:
        raise ValueError("Domaine vide")

    resp = http_requests.get(
        CRTSH_URL,
        params={'q': name, 'output': 'json'},
        timeout=timeout,
        headers={'User-Agent': 'Sentinelle-CT/1.0'},
    )
    if resp.status_code != 200:
        raise ValueError(f"crt.sh a repondu HTTP {resp.status_code}")

    try:
        rows = resp.json()
    except ValueError:
        # crt.sh renvoie parfois un corps vide quand il n'a aucun resultat.
        if not (resp.text or '').strip():
            return []
        raise ValueError("Reponse crt.sh illisible (JSON attendu)")

    by_id = {}
    for row in rows or []:
        cert = _normalize(row)
        if cert:
            by_id[cert['crtsh_id']] = cert
    return [by_id[k] for k in sorted(by_id)]
