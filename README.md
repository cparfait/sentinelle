<div align="center">

# 🛡️ Sentinelle

**La météo de votre DSI — supervision proactive des échéances et de la conformité.**

[![CI](https://github.com/cparfait/sentinelle/actions/workflows/ci.yml/badge.svg)](https://github.com/cparfait/sentinelle/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-black)
![Licence](https://img.shields.io/badge/usage-interne-lightgrey)

</div>

---

Sentinelle est un tableau de bord web qui surveille, **en un coup d'œil**, les points qui font mal
quand on les oublie dans une DSI : mots de passe à renouveler, certificats TLS et noms de domaine
qui expirent, sauvegardes non vérifiées, tests récurrents (PRA…), revues de droits et mises à jour
applicatives. Le tout avec des **alertes automatiques** (mail + Teams), un **récap quotidien**, une
**traçabilité complète** et une **gestion fine des accès**.

## ✨ Fonctionnalités

### Surveillance
- **Comptes** — rotation des mots de passe (avec **synchro de l'expiration depuis Active Directory**).
- **Certificats** — expiration TLS, **lecture automatique de la date réelle** en se connectant au domaine.
- **Domaines** — expiration des noms de domaine via **RDAP** (successeur du WHOIS).
- **Backups** — check quotidien, **détection de retard selon la fréquence** (quotidien/hebdo/mensuel),
  **connecteur mail** (lit les comptes-rendus Veeam / scripts déposés dans un dossier ou poussés par webhook).
- **Tests** — activités récurrentes (restauration, PCA/PRA, intégrité…).
- **Revue de droits** — revue périodique des accès aux applications métiers.
- **Mises à jour** — suivi des versions et du statut (à jour / disponible / critique) + qui a fait la MàJ.

### Pilotage & alertes
- **Tableau de bord** : conformité globale (%), compteurs par catégorie, éléments urgents.
- **Récap quotidien** par mail, **alertes** par seuils (mail + **Microsoft Teams**), avec **anti-doublon** et **report (snooze)**.
- **Page « À venir »** (agenda des échéances) et **Tendances** (graphes 30 jours).
- **Seuils d'alerte configurables**, **liens cliquables** dans les mails.

### Sécurité & exploitation
- **Rôles & permissions granulaires** par catégorie (Aucun / Lecture / Écriture / Suppression) + **rôles personnalisés**.
- **Authentification hybride** : comptes locaux **et** LDAP/Active Directory (**LDAPS** géré), en même temps.
- **2FA (TOTP)**, **verrouillage** après N échecs, **expiration de session**, **politique de mot de passe**.
- **Journal d'audit** complet (qui a fait quoi), paginé et cherchable.
- **Corbeille** (restauration + suppression définitive), **import/export CSV**, **bilan PDF (COPIL)**.
- **Auto-sauvegarde** de la base + **export total de secours** (clé USB), **logs applicatifs** avec rotation.

## 🧱 Stack

Flask 3 · SQLAlchemy · Flask-Login · Flask-WTF (CSRF) · APScheduler · Bootstrap 5 · Chart.js ·
reportlab (PDF) · ldap3 (AD) · pyotp/qrcode (2FA) · waitress (prod). Base **SQLite**.
**Aucune dépendance Internet à l'exécution** (assets servis en local).

## 🚀 Installation (développement)

> Nécessite **Python 3.13**.

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # puis éditer .env (voir ci-dessous)
python run.py                 # http://127.0.0.1:5000
```

Au **premier démarrage**, un compte `admin` est créé avec un **mot de passe aléatoire affiché une
seule fois dans la console** (ou via `ADMIN_INITIAL_PASSWORD`). Connectez-vous puis changez-le.

## ▶️ Lancement en production

```powershell
.\venv\Scripts\python.exe run_prod.py     # serveur WSGI waitress
```

- ⚠️ **Un seul process** : le planificateur d'alertes tourne *dans* l'application ; waitress
  fonctionne en **1 process multi-threads**, ce qui garantit l'**absence d'alertes en double**.
  Ne lancez pas plusieurs instances en parallèle.
- Mettez `APP_DEBUG=false` et un **`SECRET_KEY` fort** (le démarrage est refusé sinon, hors debug).
- Pour tourner en continu : déclarez `run_prod.py` comme **service** (Tâche planifiée Windows au
  démarrage, NSSM, ou systemd sous Linux).

## ⚙️ Configuration (`.env`)

Voir [`.env.example`](.env.example). Principaux réglages :

| Variable | Rôle |
|---|---|
| `SECRET_KEY` | Clé de session (obligatoire en prod). `python -c "import secrets;print(secrets.token_hex(32))"` |
| `APP_BASE_URL` | URL publique de l'app (liens cliquables dans les mails) |
| `MAIL_METHOD` / `MAIL_SERVER`… | Envoi mail : **SMTP** ou **Direct Send M365** (sans auth) |
| `ALERT_RECIPIENTS` | Destinataires des alertes (gérables aussi dans l'UI) |
| `TEAMS_WEBHOOK_URL` | Webhook Teams (notifications en plus du mail) |
| `LDAP_*` | Authentification AD / LDAPS, compte de service pour la synchro mdp |
| `THRESHOLD_*` | Seuils de statut (jours) par groupe |
| `BACKUP_INBOX_DIR` / `BACKUP_INGEST_TOKEN` | Connecteurs backup (dossier / webhook) |
| `BACKUP_DB_DIR` / `BACKUP_DB_KEEP` | Auto-sauvegarde de la base |
| `SESSION_LIFETIME_MINUTES`, `PASSWORD_MIN_LENGTH`, `LOGIN_*` | Sécurité |

> La plupart de ces réglages sont aussi modifiables **dans l'interface** (Préférences, réservé admin).

## 🔐 Rôles & accès

| Rôle (par défaut) | Droits |
|---|---|
| **Administrateur** | Tout, y compris utilisateurs, rôles, préférences |
| **Éditeur** | Création / modification / suppression des données |
| **Lecteur** | Lecture seule |

Les rôles sont **éditables** et on peut **créer des rôles personnalisés** (matrice par catégorie)
dans *Rôles & permissions*. Authentification **locale + LDAP/AD** simultanées ; **2FA** activable
par chaque utilisateur depuis son profil.

## ⏰ Tâches planifiées (quotidiennes)

| Heure | Tâche |
|---|---|
| 01h00 | Auto-sauvegarde de la base |
| 06h00 | Synchro expiration mots de passe AD *(si configuré)* |
| 07h00 / 07h10 | Rafraîchissement TLS des certificats / RDAP des domaines |
| 07h30 | Envoi du récap quotidien |
| 08h00–08h55 | Alertes (mots de passe, certificats, backups, tests, domaines, revues, MàJ) |
| toutes les 30 min | Scan du dossier de mails de backup *(si configuré)* |

État et historique d'exécution visibles dans *Tâches planifiées* (admin).

## 🗂️ Structure du projet

```
app/
  __init__.py        # application factory, contexte, seeds, auto-migration SQLite
  models.py          # modèles + logique de statut (couleurs) + permissions
  auth.py            # login (local + LDAP + 2FA), profil, préférences
  accounts.py certificates.py domains.py backups.py tests.py reviews.py updates.py  (blueprints)
  alerts.py          # envoi d'alertes (mail + Teams), snooze
  scheduler.py       # jobs APScheduler
  email_service.py   # SMTP / Direct Send / Microsoft Graph
  ldap_auth.py       # LDAP/AD (auth, LDAPS, synchro mdp)
  notify.py          # webhook Teams
  cert_checker.py / domain_checker.py   # TLS / RDAP
  backup_ingest.py   # connecteur mails de backup
  csv_io.py / data_io.py   # import / export CSV
  pdf_report.py / digest.py / trash.py / audit.py / paging.py
  decorators.py      # RBAC (require_edit / require_delete / view_guard)
  templates/ static/ (dont static/vendor : assets hors-ligne)
config.py · run.py (dev) · run_prod.py (waitress) · ci_smoke.py
tools/devmail.py     # serveur SMTP de test local
```

## 🧰 Outils & exploitation

- **Tester l'envoi de mail hors réseau** : `python tools/devmail.py` (faux serveur SMTP local sur `:1025`),
  puis Préférences → SMTP = `localhost:1025`.
- **Sauvegarde / restauration** : auto-sauvegarde quotidienne + bouton *Export complet* (ZIP base + CSV +
  page HTML consultable hors-ligne) à garder sur clé USB.
- **CI** : compilation + smoke test à chaque push (voir l'onglet *Actions*).

## 📌 Notes
- Pas de migrations : `db.create_all()` au démarrage **+ auto-migration SQLite** (ajout des colonnes manquantes).
- Données sensibles (`.env`, base, tokens, sauvegardes, logs) **exclues du dépôt**.
- Langue de l'interface : **français**.

---

<div align="center"><sub>Sentinelle — outil interne de supervision DSI.</sub></div>
