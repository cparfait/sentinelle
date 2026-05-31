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

## Exploitation & fiabilité de l'outil
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
