"""Envoi d'un message de test sur le webhook Teams configure.

Usage :
    .\venv\Scripts\python.exe scripts\test_teams.py

Lit TEAMS_WEBHOOK_URL depuis la config effective (.env + overrides base),
envoie une carte de test via app.notify.send_teams et affiche le resultat.
"""
from app import create_app
from app import notify

app = create_app()
with app.app_context():
    url = app.config.get('TEAMS_WEBHOOK_URL') or ''
    if not url:
        print('KO : aucune URL Teams configuree (.env ou AppConfig).')
        raise SystemExit(1)

    if 'logic.azure' in url or 'powerautomate' in url:
        kind = 'Workflow (perenne)'
    elif 'webhook.office' in url or 'outlook.office' in url:
        kind = 'ANCIEN connecteur (deprecie -- a migrer vers Workflows)'
    else:
        kind = 'inconnu'
    print('URL detectee, type :', kind)

    ok = notify.send_teams(
        subject='Test de notification',
        body='Ceci est un message de test envoye par Sentinelle.\n'
             'Si tu le vois dans Teams, le canal fonctionne.',
        status='info',
        url=None,
    )
    print('Envoi Teams :', 'OK (HTTP 2xx)' if ok else 'KO -- voir les logs (HTTP 4xx/5xx ?)')
