"""Notifications vers un canal Microsoft Teams via Incoming Webhook (optionnel)."""
import requests as http_requests
from flask import current_app

_THEME = {'danger': 'EF4444', 'warning': 'F59E0B', 'info': '3B82F6', 'success': '10B981'}


def teams_enabled():
    return bool(current_app.config.get('TEAMS_WEBHOOK_URL'))


def send_teams(subject, body, status='danger', url=None):
    """Poste une carte dans le canal Teams configure. Best-effort : renvoie
    True/False sans lever d'exception (ne doit pas casser le flux d'alerte)."""
    webhook = current_app.config.get('TEAMS_WEBHOOK_URL')
    if not webhook:
        return False
    card = {
        '@type': 'MessageCard',
        '@context': 'http://schema.org/extensions',
        'themeColor': _THEME.get(status, '4F46E5'),
        'summary': subject,
        'title': f'[Sentinelle] {subject}',
        'text': (body or '').replace('\n', '\n\n'),
    }
    if url:
        card['potentialAction'] = [{
            '@type': 'OpenUri', 'name': 'Voir la fiche',
            'targets': [{'os': 'default', 'uri': url}],
        }]
    try:
        r = http_requests.post(webhook, json=card, timeout=15)
        if r.status_code not in (200, 202):
            current_app.logger.warning('Teams a repondu HTTP %s', r.status_code)
            return False
        return True
    except Exception as e:
        current_app.logger.warning('Envoi Teams echoue : %s', e)
        return False
