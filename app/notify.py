"""Notifications multi-canaux (Microsoft Teams, Slack, Discord) via webhooks.

Deux sources de webhooks :
  - globaux, configures dans .env / config (TEAMS/SLACK/DISCORD_WEBHOOK_URL) ;
  - par categorie de gestion, stockes en base (modele Webhook), permettant
    plusieurs webhooks par categorie (comptes, certificats, ...).

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


# ---- Constructeurs de payload par canal ----
def _teams_payload(subject, body, status, url):
    card = {
        '@type': 'MessageCard', '@context': 'http://schema.org/extensions',
        'themeColor': _color(status), 'summary': subject,
        'title': f'[Sentinelle] {subject}', 'text': (body or '').replace('\n', '\n\n'),
    }
    if url:
        card['potentialAction'] = [{'@type': 'OpenUri', 'name': 'Voir la fiche',
                                     'targets': [{'os': 'default', 'uri': url}]}]
    return card


def _slack_payload(subject, body, status, url):
    text = body or ''
    if url:
        text += f'\n<{url}|Voir la fiche>'
    return {'attachments': [{
        'color': '#' + _color(status),
        'title': f'[Sentinelle] {subject}',
        'text': text, 'mrkdwn_in': ['text'],
    }]}


def _discord_payload(subject, body, status, url):
    embed = {
        'title': f'[Sentinelle] {subject}',
        'description': body or '',
        'color': int(_color(status), 16),
    }
    if url:
        embed['url'] = url
    return {'embeds': [embed]}


_BUILDERS = {'teams': _teams_payload, 'slack': _slack_payload, 'discord': _discord_payload}


def send_to(channel, webhook_url, subject, body, status='danger', url=None):
    """Envoie sur un canal donne (teams/slack/discord) vers une URL precise."""
    builder = _BUILDERS.get(channel)
    if not builder or not webhook_url:
        return False
    return _post(webhook_url, builder(subject, body, status, url))


# ---- Webhooks globaux (config) — retro-compatibilite ----
def teams_enabled():
    return bool(current_app.config.get('TEAMS_WEBHOOK_URL'))


def slack_enabled():
    return bool(current_app.config.get('SLACK_WEBHOOK_URL'))


def discord_enabled():
    return bool(current_app.config.get('DISCORD_WEBHOOK_URL'))


def send_teams(subject, body, status='danger', url=None):
    return send_to('teams', current_app.config.get('TEAMS_WEBHOOK_URL'), subject, body, status, url)


def send_slack(subject, body, status='danger', url=None):
    return send_to('slack', current_app.config.get('SLACK_WEBHOOK_URL'), subject, body, status, url)


def send_discord(subject, body, status='danger', url=None):
    return send_to('discord', current_app.config.get('DISCORD_WEBHOOK_URL'), subject, body, status, url)


def notify_all(subject, body, status='danger', url=None, category=None):
    """Diffuse vers les webhooks globaux (config) et, si une categorie est
    fournie, vers les webhooks de cette categorie (et ceux marques 'all').
    Retourne le nombre d'envois reussis."""
    sent = 0
    # 1) Webhooks globaux issus de la config
    for fn in (send_teams, send_slack, send_discord):
        try:
            if fn(subject, body, status=status, url=url):
                sent += 1
        except Exception:
            pass
    # 2) Webhooks en base, par categorie (+ 'all')
    try:
        from app.models import Webhook
        cats = ['all']
        if category:
            cats.append(category)
        rows = Webhook.query.filter(Webhook.is_active.is_(True),
                                    Webhook.category.in_(cats)).all()
        for w in rows:
            try:
                if send_to(w.channel, w.url, subject, body, status=status, url=url):
                    sent += 1
            except Exception:
                pass
    except Exception:
        pass
    return sent
