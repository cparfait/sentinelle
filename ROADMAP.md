# Feuille de route — Sentinelle

Suivi des évolutions demandées. Légende : ✅ fait · 🚧 en cours · ⬜ à faire.

## Surveillance & automatisation
- ✅ **Vérif auto des certificats TLS** — lecture de la date d'expiration réelle (fiche + job 7h00 + **fiche de création**).
- ✅ **Détection backup en retard** — statut calculé selon la fréquence (quotidien/hebdo/mensuel) + tolérance, au lieu de supposer du quotidien.
- ✅ **Connecteurs backup** — connecteur **dossier** (scan auto 30 min + bouton « Scanner la boîte », archive `traites/`) et endpoint `POST /backups/ingest` (jeton). Analyseur calibré sur les mails réels : tag `[Success]/[Warning]/[Failed]` Veeam, mots‑clés en mots entiers (piège « Ko » évité), et succès implicite pour les rapports « Sauvegarde … » sans erreur. ⚠️ Nommer les backups dans Sentinelle pour que le nom soit contenu dans l'objet du mail (ex. `PC-SYGAAL`, `WWW VPS`, `Backup_Chatillon_VM`).
- ✅ **Expiration de noms de domaine** — nouvelle section **Domaines** (modèle, CRUD, fiche, dashboard, alertes), lecture auto via **RDAP** (bouton + fiche de création + job 7h10), snooze, intégré au récap.

## Alertes & notifications
- ✅ **Récap quotidien par mail** — un seul mail le matin (job 7h30) + liens cliquables.
- ✅ **Acquittement / report (snooze)** — mise en pause par élément (7/30/90 j).
- ⬜ **Seuils d'alerte configurables** — J‑30/15/7… paramétrables (global ou par élément).
- ⬜ **Anti-doublon d'alertes** — ne pas renvoyer une alerte déjà notifiée.

## Reporting & visualisation
- ✅ **Export CSV** — bouton « CSV » sur chaque liste (comptes, certificats, domaines, backups, tests) : export UTF‑8/Excel‑FR.
- ⬜ **Vue tendances** — évolution des statuts dans le temps (graphes).
- ⬜ **Page « à venir cette semaine / ce mois »** — agenda des échéances.
- ⬜ **Widgets dashboard** — taux de conformité, top urgences, compteurs.

## Exploitation & fiabilité de l'outil
- ⬜ **Historique d'exécution du scheduler** — tracer chaque run des jobs.
- ✅ **Import CSV** — import en masse depuis le bouton « CSV » de chaque liste + **modèle d'import téléchargeable** (détection séparateur, dates JJ/MM/AAAA ou AAAA‑MM‑JJ).
- ✅ **Auto-sauvegarde de la base SQLite** — copie horodatée cohérente (API sqlite3) quotidienne (01h00) + rotation (N copies) + bouton « Sauvegarder maintenant », liste et **suppression** dans Préférences.
- ✅ **Export total de secours (clé USB)** — archive ZIP (base + CSV + page HTML consultable hors-ligne + LISEZMOI) pour PRA en cas de crash/attaque. Bouton « Export complet » (admin).
- ⬜ **Fichier de logs applicatif** — journalisation avec rotation (au lieu du print console).

## Sécurité & conformité
- ✅ **Finir le rôle « lecture seule »** — boutons d'édition/création/suppression, import CSV, snooze, check rapide et colonnes d'actions des fiches masqués pour les viewers (RBAC déjà appliqué côté serveur). Export CSV reste accessible.
- ✅ **Verrouillage après N échecs de login** — table `LoginThrottle`, blocage temporaire configurable (`LOGIN_MAX_ATTEMPTS`=5, `LOGIN_LOCKOUT_MINUTES`=15), messages d'erreur désormais affichés sur la page de login.
- ⬜ **Journal d'audit global** — vue centralisée « qui a modifié quoi ».
- ⬜ **2FA (TOTP) pour les admins**.
- ⬜ **Politique de mot de passe + expiration des sessions**.

## Ergonomie / UX
- ⬜ **Tri & filtres** sur les listes (statut, priorité, échéance).
- ⬜ **Pagination / recherche** dans les longues listes.
- ✅ **Badges de compteur** dans la sidebar — nombre d'éléments critiques (rouges) par section (comptes, certificats, domaines, backups, tests).
- ⬜ **Confirmation de suppression uniformisée + corbeille** (restaurer un élément désactivé).

## Technique / intégrations
- ⬜ **Retirer Flask‑Mail** (devenu inutile depuis le passage à smtplib/Direct Send).
- ⬜ **LDAP / Active Directory** — authentification avec le compte mairie.
- ⬜ **Synchronisation des comptes AD** — expiration réelle des mots de passe AD.

---

### Déjà livré hors de cette liste (rappel)
Corrections scheduler · sécurité (CSRF, RBAC, secret/admin) · git + doc · logo SVG ·
messagerie SMTP/Direct Send (UTF‑8, expéditeur, config vivante) · modèle HTML d'alerte ·
gestion des destinataires dans l'UI · `tools/devmail.py` (serveur SMTP de test local).
