"""Tests des payloads de notification webhook (Teams surtout).

Verifie le choix de format Teams selon l'URL :
  - Workflow (Power Automate) -> Adaptive Card, format perenne ;
  - ancien connecteur O365 -> repli MessageCard, retro-compatibilite.
"""
from app import notify


def test_teams_workflow_url_produit_adaptive_card(app):
    url = 'https://prod-1.francecentral.logic.azure.com/workflows/a/triggers/manual/paths/invoke'
    payload = notify._teams_payload('Sujet', 'Corps', 'danger', 'https://s/fiche/1', url)

    assert payload['type'] == 'message'
    att = payload['attachments'][0]
    assert att['contentType'] == 'application/vnd.microsoft.card.adaptive'
    card = att['content']
    assert card['type'] == 'AdaptiveCard'
    # Titre colore selon le statut, action « Voir la fiche » presente.
    assert card['body'][0]['color'] == 'attention'
    assert card['actions'][0]['type'] == 'Action.OpenUrl'
    assert card['actions'][0]['url'] == 'https://s/fiche/1'


def test_teams_ancien_connecteur_produit_messagecard(app):
    url = 'https://contoso.webhook.office.com/webhookb2/xyz@tid/IncomingWebhook/abc'
    payload = notify._teams_payload('Sujet', 'Corps', 'warning', None, url)

    assert payload['@type'] == 'MessageCard'
    assert payload['themeColor'] == notify._color('warning')


def test_teams_sans_url_defaut_workflow(app):
    # URL inconnue / vide -> on vise le format perenne (Adaptive Card).
    payload = notify._teams_payload('Sujet', 'Corps', 'info', None, 'https://exemple.test/hook')
    assert payload['type'] == 'message'


def test_send_to_teams_utilise_le_bon_format(app, monkeypatch):
    captures = {}
    monkeypatch.setattr(notify, '_post', lambda u, p: captures.setdefault('p', p) or True)

    notify.send_to('teams', 'https://x.logic.azure.com/workflows/i', 'S', 'B', 'success', None)
    assert captures['p']['type'] == 'message'
