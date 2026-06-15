# Feuille de route — Sentinelle

Suivi des évolutions demandées. Légende : ✅ fait · 🚧 en cours · ⬜ à faire.

## Modules métier
- ✅ **Revue de droits** — revue périodique des accès aux applications métiers (activité récurrente : application, responsable, périmètre, cadence, prochaine revue, statut). Alertes, agenda, snooze, CSV, RBAC.
- ✅ **Mises à jour** — suivi des MàJ applications/systèmes (statut manuel À jour / MàJ disponible / Critique + versions). Bouton « Marquer à jour », alertes critiques, snooze, CSV, RBAC.

## Surveillance & automatisation
- ✅ **Vérif auto des certificats TLS** — lecture de la date d'expiration réelle (fiche + job 7h00 + **fiche de création**).
- ✅ **Détection backup en retard** — statut calculé selon la fréquence (quotidien/hebdo/mensuel) + tolérance, au lieu de supposer du quotidien.
- ✅ **Connecteurs backup** — connecteur **dossier** (scan auto 30 min + bouton « Scanner la boîte », archive `traites/`) et endpoint `POST /backups/ingest` (jeton). Analyseur calibré sur les mails réels : tag `[Success]/[Warning]/[Failed]` Veeam, mots‑clés en mots entiers (piège « Ko » évité), et succès implicite pour les rapports « Sauvegarde … » sans erreur. ⚠️ Nommer les backups dans Sentinelle pour que le nom soit contenu dans l'objet du mail (ex. `PC-SYGAAL`, `WWW VPS`, `Backup_Chatillon_VM`).
- ✅ **Expiration de noms de domaine** — nouvelle section **Domaines** (modèle, CRUD, fiche, dashboard, alertes), lecture auto via **RDAP** (bouton + fiche de création + job 7h10), snooze, intégré au récap.

## Alertes & notifications
- ✅ **Récap quotidien par mail** — un seul mail le matin (job 7h30) + liens cliquables.
- ✅ **Acquittement / report (snooze)** — mise en pause par élément (7/30/90 j).
- ✅ **Seuils d'alerte configurables** — seuils de statut (jours restants : critique/attention/proche) paramétrables par groupe (comptes&certifs, domaines, tâches) via Préférences + `.env`.
- ✅ **Anti-doublon d'alertes** — `send_alert` idempotent : une seule alerte par élément et par jour (vérifie l'historique `AlertLog`).

## Reporting & visualisation
- ✅ **Export CSV** — bouton « CSV » sur chaque liste (comptes, certificats, domaines, backups, tests) : export UTF‑8/Excel‑FR.
- ✅ **Vue tendances** — page « Tendances » (Chart.js) : répartition globale par statut, alertes envoyées/jour et checks de backup/jour sur 30 jours, filtrée selon les droits.
- ✅ **Page « À venir »** — agenda des échéances (rotations MDP, certificats, domaines, tests) groupé par horizon (en retard / cette semaine / ce mois / 90 j), filtré selon les droits.
- ✅ **Widgets dashboard** — bandeau de **conformité globale** (% OK + barre de progression + compteurs cliquables), en plus des cartes par catégorie et de la liste des urgences déjà présentes.
- ✅ **Export PDF « bilan COPIL »** — bouton « Bilan PDF » : conformité globale, tableau par catégorie et éléments à traiter (reportlab), filtré selon les droits.

## Modules métier (suite)
- ✅ **Vue serveur 360°** — liaison optionnelle des certificats, sauvegardes et mises à jour à un équipement de l'inventaire (`equipment_id`). Select dans les formulaires, lien sur les fiches, section « Éléments liés » sur la fiche équipement. Un backup actif lié couvre désormais l'alerte « criticité élevée sans sauvegarde ».

## Exploitation & fiabilité de l'outil
- ✅ **Sonde `/healthz`** — endpoint non authentifié pour la supervision (Zabbix/Centreon/NinjaOne) : app + base + scheduler (dernier job < 26 h). 200 = OK, 503 = problème.
- ✅ **Calendrier ICS : téléchargement + abonnement** — bouton « Télécharger (.ics) » sur la page À venir, et **lien d'abonnement personnel** (jeton `User.ics_token`, génération/régénération/désactivation depuis la page) : Outlook/Thunderbird récupèrent le flux `/agenda.ics?token=…` automatiquement, filtré selon les droits du propriétaire du jeton. Plus besoin de réexporter.
- ✅ **Corbeille : équipements restaurables** — l'inventaire est désormais géré par la page corbeille (restauration tracée dans le journal d'audit, purge avec détachement des certificats/backups/MàJ liés). Corrige l'incohérence badge sidebar vs page.
- ✅ **Vue 360° : champ équipement au CSV** — colonne `equipment` (par nom) à l'import/export CSV des certificats, sauvegardes et mises à jour.
- ✅ **Vue 360° : contrats** — contrats rattachés à un équipement intégrés à la section « Éléments liés » de la fiche et aux échéances de l'agenda.
- ✅ **Agenda enrichi** — fins de garantie matérielle et fins de support OS (EOL) ajoutées aux échéances de la page À venir et au flux ICS.
- ✅ **2FA obligatoire pour les admins** — option `REQUIRE_2FA_ADMIN` : un administrateur sans TOTP est contraint de l'activer avant tout accès.
- ✅ **Anti-bruteforce par IP** — le blocage du login est désormais indexé sur le couple (identifiant, IP source) : un tiers ne peut plus verrouiller le compte d'un collègue à distance (déni de service ciblé).
- ✅ **Bilan PDF planifié** — envoi automatique du bilan de supervision (hebdomadaire/mensuel) aux destinataires configurés.
- ✅ **Suite pytest** — `tests/` : paliers de statuts (comptes, certificats, domaines, tests, revues, garanties), fréquences de backup + tolérance, politique de rappel d'alertes, snooze, healthz, ICS, vue 360° (29 tests). Intégrée à la CI.
- ✅ **Rattrapage d'alertes** — fin des déclenchements à jours exacts (30, 15, 7…) : une alerte ratée (job en erreur, serveur éteint) est désormais rattrapée. Rappel tous les 7 j en zone attention, 2 j en zone critique, quotidien une fois l'échéance dépassée (`should_send_reminder`, basé sur `AlertLog`). Fenêtres alignées sur les seuils configurés (`THRESHOLD_*`).
- ✅ **Tolérance de retard des jobs** — `misfire_grace_time=1h` + `coalesce` sur tous les jobs APScheduler : un job en retard s'exécute quand même au lieu d'être perdu pour la journée.
- ✅ **SQLite durci pour le multi-thread** — `journal_mode=WAL` + `busy_timeout=5s` (waitress 8 threads), plus d'erreurs `database is locked`.
- ✅ **Index de base** — FK des historiques, `BackupCheck.check_date`, `AlertLog` (entité + date), `ActionLog.performed_at` ; créés automatiquement sur les bases existantes via `_auto_migrate_sqlite`.
- ✅ **Performance des pages** — compteurs de la sidebar en cache (60 s) au lieu d'un rechargement complet de la base à chaque requête ; rôle utilisateur chargé une fois par requête (`flask.g`) ; statuts du dashboard calculés une seule fois par objet ; page Tendances en 2 requêtes groupées au lieu de 60.
- ✅ **En-têtes de sécurité HTTP** — CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy` sur toutes les réponses ; `SESSION_COOKIE_SECURE` activable via `.env` (recommandé derrière un reverse proxy TLS).

- ✅ **Historique d'exécution du scheduler** — page admin « Tâches planifiées » : prochaines exécutions + dernières exécutions (succès/erreur) via un écouteur APScheduler (`SchedulerRun`, purge à 500).
- ✅ **Import CSV** — import en masse depuis le bouton « CSV » de chaque liste + **modèle d'import téléchargeable** (détection séparateur, dates JJ/MM/AAAA ou AAAA‑MM‑JJ).
- ✅ **Auto-sauvegarde de la base SQLite** — copie horodatée cohérente (API sqlite3) quotidienne (01h00) + rotation (N copies) + bouton « Sauvegarder maintenant », liste et **suppression** dans Préférences.
- ✅ **Export total de secours (clé USB)** — archive ZIP (base + CSV + page HTML consultable hors-ligne + LISEZMOI) pour PRA en cas de crash/attaque. Bouton « Export complet » (admin).
- ✅ **Fichier de logs applicatif** — journalisation avec rotation dans `instance/logs/sentinelle.log` (RotatingFileHandler).

## Sécurité & conformité
- ✅ **Rôles & permissions granulaires** — rôles par défaut (admin/editor/viewer) **+ rôles personnalisés**, droits par catégorie (Aucun / Lecture / Écriture / Suppression), appliqués aux routes (lecture, écriture, suppression), au menu, aux boutons et à l'import CSV. Page d'admin « Rôles & permissions ».
- ✅ Listes mises en avant : tri par criticité + surlignage + filtres interactifs par statut.
- ✅ **Finir le rôle « lecture seule »** — boutons d'édition/création/suppression, import CSV, snooze, check rapide et colonnes d'actions des fiches masqués pour les viewers (RBAC déjà appliqué côté serveur). Export CSV reste accessible.
- ✅ **Verrouillage après N échecs de login** — table `LoginThrottle`, blocage temporaire configurable (`LOGIN_MAX_ATTEMPTS`=5, `LOGIN_LOCKOUT_MINUTES`=15), messages d'erreur désormais affichés sur la page de login.
- ✅ **Journal d'audit global** — vue chronologique unifiée des historiques (comptes, certificats, domaines, backups, tests), réservée aux admins.
- ✅ **2FA (TOTP)** — activable par chaque utilisateur depuis son profil (QR code pyotp/qrcode), vérification d'un code à la connexion, désactivation protégée par mot de passe.
- ✅ **Politique de mot de passe + expiration des sessions** — longueur minimale configurable (`PASSWORD_MIN_LENGTH`), déconnexion auto après inactivité (`SESSION_LIFETIME_MINUTES`, défaut 8 h), cookies durcis (HttpOnly, SameSite=Lax).

## Ergonomie / UX
- ✅ **Tri & filtres** sur les listes — tri automatique par criticité + surlignage + **filtres interactifs par statut** (barre Tous/Critique/Attention/À surveiller/OK générée en JS sur les tableaux `js-filterable`).
- ✅ **Pagination / recherche** — journal d'audit (50/page + recherche plein-texte). Les listes métier disposent du tri + filtres par statut (volumes modestes).
- ✅ **Badges de compteur** dans la sidebar — nombre d'éléments critiques (rouges) par section (comptes, certificats, domaines, backups, tests).
- ✅ **Corbeille** — page listant les éléments supprimés (désactivés) par catégorie, avec restauration (droit d'édition) et **suppression définitive** / **vider la corbeille** (droit de suppression). Confirmations en place.

## Technique / intégrations
- ✅ **Retirer Flask‑Mail** — supprimé (code + dépendance), l'envoi passe par smtplib directement.
- ✅ **CI GitHub Actions** — workflow `.github/workflows/ci.yml` : install deps + compilation + smoke test (`ci_smoke.py`) à chaque push/PR.
- ✅ **LDAP / Active Directory** — authentification **hybride** : mot de passe local d'abord, puis bind LDAP/AD (ldap3). **LDAPS** géré (port 636 auto, TLS, validation du certificat activable, CA interne/auto‑signé pris en charge). Utilisateurs AD provisionnés automatiquement. Configurable dans Préférences. Comptes locaux et AD en même temps.
- ✅ **Synchronisation des comptes AD** — synchro de l'expiration réelle des mots de passe depuis l'AD (`msDS-UserPasswordExpiryTimeComputed`) via un compte de service : job quotidien (6h00) + bouton « Synchroniser AD » sur la liste des comptes.

---

### Déjà livré hors de cette liste (rappel)
Corrections scheduler · sécurité (CSRF, RBAC, secret/admin) · git + doc · logo SVG ·
messagerie SMTP/Direct Send (UTF‑8, expéditeur, config vivante) · modèle HTML d'alerte ·
gestion des destinataires dans l'UI · `tools/devmail.py` (serveur SMTP de test local).
