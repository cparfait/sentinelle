# Sentinelle — Météo de la DSI

Tableau de bord interne de supervision pour une DSI. Sentinelle donne en un coup d'œil
la « météo » opérationnelle et envoie des alertes mail avant que les échéances ne deviennent
critiques.

## Ce qui est suivi

| Domaine | Suivi |
|---|---|
| **Comptes** | Rotation des mots de passe (échéance selon `rotation_days`) |
| **Certificats** | Dates d'expiration TLS, auto-renouvellement |
| **Backups** | Check quotidien manuel, taux de réussite, série (« streak ») |
| **Tests** | Tests récurrents : restauration, PCA/PRA, intégrité… |
| **Alertes** | Historique des notifications envoyées |

Un tableau de bord agrège les statuts (vert / info / orange / rouge) et liste les éléments urgents.

## Stack

Flask 3 · SQLAlchemy · Flask-Login · Flask-WTF (CSRF) · APScheduler · Bootstrap 5.
Base de données SQLite par défaut. Envoi de mail via **SMTP** ou **Microsoft Graph (Office 365 / OAuth2)**.

## Installation

> Nécessite Python 3.13 (le venv du dépôt a été créé avec cette version).

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # puis éditer .env
python run.py
```

L'application écoute par défaut sur http://127.0.0.1:5000.

## Configuration (`.env`)

Voir [.env.example](.env.example). Points importants :

- **`SECRET_KEY`** : doit être une valeur forte. En dehors du mode debug, l'application
  refuse de démarrer si la clé est restée une valeur de dev.
  Générer : `python -c "import secrets; print(secrets.token_hex(32))"`
- **`MAIL_METHOD`** : `smtp` ou `o365`. La config O365 se fait ensuite dans l'UI
  (Préférences, réservé aux admins).
- **`ALERT_RECIPIENTS`** : destinataires des alertes, séparés par des virgules.
- **`ADMIN_INITIAL_PASSWORD`** (optionnel) : mot de passe initial du compte `admin`.

## Premier démarrage / compte admin

Au premier lancement, un compte `admin` est créé avec un **mot de passe aléatoire affiché
une seule fois dans la console** (ou la valeur de `ADMIN_INITIAL_PASSWORD` si définie).
Si un ancien compte `admin` possède encore le mot de passe par défaut `admin`, il est
automatiquement réinitialisé (nouveau mot de passe affiché dans la console).

Connectez-vous puis changez le mot de passe via votre profil.

## Rôles

- **admin** : tout, y compris gestion des utilisateurs et des préférences mail.
- **editor** : peut créer / modifier / supprimer comptes, certificats, backups, tests.
- **viewer** : lecture seule.

## Tâches planifiées

APScheduler envoie chaque matin les alertes (mots de passe 08:00, certificats 08:15,
backups 08:30, tests 08:45). Le scheduler démarre avec l'application
(`start_scheduler(app)` dans `app/__init__.py`).

## Schéma de base de données

Le schéma est créé automatiquement via `db.create_all()` au démarrage. Pas de système
de migrations (Flask-Migrate a été retiré). Pour faire évoluer le schéma sur une base
existante, recréer la base ou appliquer le changement manuellement.
