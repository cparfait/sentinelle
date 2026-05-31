"""Notifications multi-canaux (Microsoft Teams, Slack, Discord) via webhooks.

Tous best-effort : aucune exception ne remonte (ne doit pas casser le flux d'alerte).
"""
import requests as http_requests
from flask import current_app

# Couleur par statut (hex sans #)
_HEX = {'danger': 'EF4444', 'warning': 'F59E0B', 'info': '3B82F6', 'success': '10B981'}


def _color(status):
    return _HEX.get(status, '4F46E5')


def _post(url, payload):
    try:
        r = http_requests.post(url, json=payload, timeout=15)
        if r.status_code not in (200, 202, 204):
            current_app.logger.warning('Notification webhook HTTP %s', r.status_code)
            return False
        return True
    except Exception as e:
        current_app.logger.warning('Envoi notification echoue : %s', e)
        return False


# ---- Microsoft Teams ----
def teams_enabled():
    return bool(current_app.config.get('TEAMS_WEBHOOK_URL'))


def send_teams(subject, body, status='danger', url=None):
    webhook = current_app.config.get('TEAMS_WEBHOOK_URL')
    if not webhook:
        return False
    card = {
        '@type': 'MessageCard', '@context': 'http://schema.org/extensions',
        'themeColor': _color(status), 'summary': subject,
        'title': f'[Sentinelle] {subject}', 'text': (body or '').replace('\n', '\n\n'),
    }
    if url:
        card['potentialAction'] = [{'@type': 'OpenUri', 'name': 'Voir la fiche',
                                     'targets': [{'os': 'default', 'uri': url}]}]
    return _post(webhook, card)


# ---- Slack ----
def slack_enabled():
    return bool(current_app.config.get('SLACK_WEBHOOK_URL'))


def send_slack(subject, body, status='danger', url=None):
    webhook = current_app.config.get('SLACK_WEBHOOK_URL')
    if not webhook:
        return False
    text = body or ''
    if url:
        text += f'\n<{url}|Voir la fiche>'
    payload = {'attachments': [{
        'color': '#' + _color(status),
        'title': f'[Sentinelle] {subject}',
        'text': text, 'mrkdwn_in': ['text'],
    }]}
    return _post(webhook, payload)


# ---- Discord ----
def discord_enabled():
    return bool(current_app.config.get('DISCORD_WEBHOOK_URL'))


def send_discord(subject, body, status='danger', url=None):
    webhook = current_app.config.get('DISCORD_WEBHOOK_URL')
    if not webhook:
        return False
    embed = {
        'title': f'[Sentinelle] {subject}',
        'description': body or '',
        'color': int(_color(status), 16),
    }
    if url:
        embed['url'] = url
    return _post(webhook, {'embeds': [embed]})


def notify_all(subject, body, status='danger', url=None):
    """Diffuse vers tous les canaux configures. Retourne le nombre d'envois reussis."""
    sent = 0
    for fn in (send_teams, send_slack, send_discord):
        try:
            if fn(subject, body, status=status, url=url):
                sent += 1
        except Exception:
            pass
    return sent
