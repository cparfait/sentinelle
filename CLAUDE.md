# CLAUDE.md

Guidance pour travailler sur ce dépôt. Voir [README.md](README.md) pour la présentation
fonctionnelle.

## Vue d'ensemble

« Sentinelle » : tableau de bord Flask de supervision d'une DSI (comptes/mots de passe,
certificats TLS et électroniques, domaines, backups, tests récurrents) **et** inventaire
du parc et des logiciels (éditeurs, marchés et pièces, devis, services utilisateurs,
pièces jointes), avec alertes mail. Usage interne, SQLite, peu d'utilisateurs.

L'application sœur « SoftInventory » a été absorbée : ses fonctionnalités et ses données
vivent ici. Il n'y a plus qu'un seul outil — ne pas réintroduire de synchro externe pour
le catalogue des logiciels.

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
  `backups`, `tests`, `alerts`, `users`, `search`, `inventory`, `software`, `contracts`,
  `suppliers`, `documents`, `referentials`.
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
- **Fonctionnalités paramétrables** : **toute nouvelle fonctionnalité doit être activable
  / désactivable depuis la page Préférences** (`auth/preferences.html` + action POST dans
  `preferences()`), avec la clé persistée via `config_store` (l'ajouter à `MANAGED`, et à
  `_BOOL` si c'est un interrupteur). Prévoir un défaut sûr et un repli `.env`/`config.py`.
  Référence : `CT_MONITORING` (surveillance Certificate Transparency). Pour un **module**
  entier (écrans + routes d'écriture), le déclarer dans `app/features.py` : il rejoint la
  rubrique *Modules* de Préférences, `features.<nom>` masque ses écrans dans les gabarits
  et `features.require('<nom>')` ferme ses routes d'écriture (404) quand il est coupé.
- **Droits** : une catégorie de permission par module (`PERMISSION_CATEGORIES`), y compris
  `software` et `suppliers`. Un blueprint nouveau se déclare dans `_BP_CATEGORY`
  (`app/decorators.py`). Une catégorie nouvelle qui remplace un droit emprunté se recopie
  une fois dans les rôles existants via `PERMISSION_INHERITANCE` et `_migrate_roles()`.
- **Liens plutôt que texte libre** : quand une fiche désigne une autre entité, porter un
  `<entité>_id` à côté du texte affiché, poser le lien à la saisie (nom exact, sans homonyme)
  et rapprocher l'existant une fois dans `_migrate_data()` sans toucher un lien déjà posé.
  Références : `AccessReview.software_id`, `Certificate.domain_id`, `Domain.registrar_id`.
- **Documents** : un fichier accroché à une fiche (`Document`, octets à part dans `DocumentContent`).
  Un document de contrat porte en plus une date, un montant et des notes : il n'existe pas de
  notion séparée de « pièce de marché ». Une ligne peut être **sans fichier** (`size` NULL,
  `has_file()` faux) quand l'acte est attendu : les routes de lecture répondent 404 et la fiche
  propose `documents.attach_file`.
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
- **Listes de valeurs** : celles dont un CALCUL dépend (cycle de vie, hébergement,
  criticité, statut de certificat) restent des constantes dans `models.py` — en ajouter
  laisserait des fiches orphelines et des filtres qui ne filtrent plus. Les libellés
  purement descriptifs vivent en base (`Referential`, écran *Référentiels*, admin).
- **Migrations de schéma SQLite** : `_auto_migrate_sqlite()` ajoute colonnes et index, mais
  ne sait NI relâcher un `NOT NULL` NI remplir les lignes existantes. Les deux se font à la
  main (cf. `_relacher_colonnes_certificat()` et les `UPDATE` de `_migrate_data()`), et une
  base ancienne échoue là où une base neuve passe — le tester sur `instance/`.
- **Dates** : utiliser `datetime.now(timezone.utc)` (déjà la convention partout).
- **Langue** : UI et messages en français.
