# CLAUDE.md

Guidance pour travailler sur ce dépôt. Voir [README.md](README.md) pour la présentation
fonctionnelle.

## Vue d'ensemble

« Sentinelle » : tableau de bord Flask de supervision d'une DSI (comptes/mots de passe,
certificats TLS, backups, tests récurrents) avec alertes mail. Usage interne, SQLite,
peu d'utilisateurs.

## Commandes

```powershell
# Environnement (Python 3.13 — l'ancien venv 3.10 a été supprimé)
.\venv\Scripts\python.exe run.py            # lancer l'app
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Vérifier qu'un fichier compile
.\venv\Scripts\python.exe -m py_compile app\<fichier>.py

# Lancer les tests
.\venv\Scripts\python.exe -m pytest -q
```

Les tests vivent sous `tests/` (fixtures dans `conftest.py`, base SQLite mémoire,
pytest dans `requirements-dev.txt`). Toute évolution de la logique de statut
(`status()`, `computed_status()`) ou de la politique d'alerte
(`should_send_reminder`) doit être couverte par un test.

## Architecture

- `run.py` → `create_app()` dans `app/__init__.py` (application factory).
- Blueprints, un par domaine : `auth`, `dashboard`, `accounts`, `certificates`,
  `backups`, `tests`, `alerts`, `users`, `search`.
- `app/models.py` : modèles SQLAlchemy. La logique de statut (vert/orange/rouge) vit dans
  les méthodes des modèles (`status()`, `computed_status()`, `success_rate()`, `streak()`).
- `app/scheduler.py` : jobs APScheduler quotidiens qui appellent `send_alert`.
- `app/email_service.py` : envoi via SMTP (Flask-Mail) ou Microsoft Graph (O365 OAuth2,
  token stocké dans `o365_token.json`).
- `app/decorators.py` : `require_edit` (admin/editor), `require_admin`.
- Templates Jinja sous `app/templates/`, assets sous `app/static/`.

## Conventions et points d'attention

- **Sécurité** : CSRF activé globalement (`CSRFProtect`). **Tout nouveau formulaire POST
  doit inclure** `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
  Toute nouvelle route qui modifie des données doit être décorée `@login_required` puis
  `@require_edit` (ou `@require_admin`).
- **Scheduler** : ne PAS appeler `create_app()` dans un job. `start_scheduler(app)` reçoit
  l'app et les jobs utilisent `with _app.app_context()`. Les jobs sont enregistrés avec
  `replace_existing=True`.
- **Base de données** : `db.create_all()` au démarrage, pas de migrations Alembic.
  `_auto_migrate_sqlite()` (dans `app/__init__.py`) ajoute automatiquement les colonnes
  et index manquants aux tables existantes — déclarer simplement le champ dans le modèle.
  Renommages et suppressions restent manuels.
- **Compte admin** : `_seed_default_user()` génère un mot de passe aléatoire (affiché en
  console) et réinitialise tout admin ayant encore le mot de passe `admin`. Ne jamais
  réintroduire un mot de passe par défaut en clair.
- **Dates** : utiliser `datetime.now(timezone.utc)` (déjà la convention partout).
- **Langue** : UI et messages en français.
