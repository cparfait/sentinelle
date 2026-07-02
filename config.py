import os
from datetime import timedelta
from dotenv import load_dotenv

# override=True : le .env fait foi, y compris apres un reload en dev (werkzeug
# reexecute le process en heritant de l'ancien environnement). Sans cela, les
# reglages enregistres via Preferences seraient perdus a chaque rechargement.
load_dotenv(override=True)


def _triplet(env, default):
    """Lit 3 entiers separes par virgule depuis l'environnement."""
    raw = os.getenv(env, '')
    try:
        parts = [int(x.strip()) for x in raw.split(',') if x.strip()]
        if len(parts) == 3:
            return tuple(parts)
    except ValueError:
        pass
    return default


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///admin_dashboard.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session : deconnexion automatique apres inactivite (minutes) + cookie durci.
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.getenv('SESSION_LIFETIME_MINUTES', 480)))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # A activer (true) des que l'app est servie en HTTPS — deploiement conseille :
    # waitress sur 127.0.0.1 derriere un reverse proxy TLS (IIS/Caddy/nginx).
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() in ('true', '1', 'yes')

    # Faire confiance a l'en-tete X-Forwarded-For pour l'IP source (anti-bruteforce).
    # A n'activer que si l'app est servie derriere un reverse proxy de confiance qui
    # positionne cet en-tete ; sinon un client peut forger son IP.
    TRUST_PROXY = os.getenv('TRUST_PROXY', 'false').lower() in ('true', '1', 'yes')

    # Longueur minimale des mots de passe.
    PASSWORD_MIN_LENGTH = int(os.getenv('PASSWORD_MIN_LENGTH', 8))

    # Authentification LDAP / Active Directory (cohabite avec le compte local).
    LDAP_ENABLED = os.getenv('LDAP_ENABLED', 'false').lower() in ('true', '1', 'yes')
    LDAP_SERVER = os.getenv('LDAP_SERVER', '')          # ex: ldap://dc.chatillon.lan
    LDAP_PORT = int(os.getenv('LDAP_PORT', 389))
    LDAP_USE_SSL = os.getenv('LDAP_USE_SSL', 'false').lower() in ('true', '1', 'yes')  # LDAPS
    # Validation du certificat serveur en LDAPS (desactiver si AD avec CA interne/auto-signe)
    LDAP_VALIDATE_CERT = os.getenv('LDAP_VALIDATE_CERT', 'true').lower() in ('true', '1', 'yes')
    LDAP_CA_CERT = os.getenv('LDAP_CA_CERT', '')  # chemin d'un fichier CA (PEM), optionnel
    LDAP_DOMAIN = os.getenv('LDAP_DOMAIN', '')           # ex: chatillon.lan (pour le bind UPN)
    LDAP_BASE_DN = os.getenv('LDAP_BASE_DN', '')         # ex: DC=exemple,DC=lan (recherche email)
    # Groupe AD dont l'appartenance est requise pour se connecter (fortement
    # conseille : limite l'acces). DN complet ou nom simple (cn). Vide = tout AD.
    LDAP_REQUIRED_GROUP = os.getenv('LDAP_REQUIRED_GROUP', '')
    LDAP_USER_DN_TEMPLATE = os.getenv('LDAP_USER_DN_TEMPLATE', '')  # alternative au bind UPN
    LDAP_DEFAULT_ROLE = os.getenv('LDAP_DEFAULT_ROLE', 'viewer')    # role des comptes AD provisionnes
    # Compte de service pour la synchro d'expiration des mots de passe AD (lecture seule).
    LDAP_BIND_USER = os.getenv('LDAP_BIND_USER', '')        # ex: svc-sentinelle@chatillon.lan
    LDAP_BIND_PASSWORD = os.getenv('LDAP_BIND_PASSWORD', '')

    # Seuils de statut en jours restants : (danger <=, attention <=, proche <=).
    THRESHOLD_EXPIRY = _triplet('THRESHOLD_EXPIRY', (7, 15, 30))   # comptes, certificats
    # Domaines volontairement plus larges que les certificats : un renouvellement
    # de domaine se prepare a l'avance (registrar, facturation) et une perte de
    # domaine est irreversible — d'ou un passage en danger des J-30.
    THRESHOLD_DOMAIN = _triplet('THRESHOLD_DOMAIN', (30, 60, 90))  # noms de domaine
    THRESHOLD_TASK = _triplet('THRESHOLD_TASK', (7, 15, 30))       # tests, revues de droits
    # Contrats : seuils larges (un renouvellement/marche public se prepare des mois
    # a l'avance) ; le statut est calcule sur (echeance - preavis de resiliation).
    THRESHOLD_CONTRACT = _triplet('THRESHOLD_CONTRACT', (60, 90, 180))
    THRESHOLD_WARRANTY = _triplet('THRESHOLD_WARRANTY', (30, 60, 90))  # fin de garantie (inventaire)
    # Au-dela de ce nombre de jours sans MAJ OS, l'equipement est signale.
    OS_STALE_DAYS = int(os.getenv('OS_STALE_DAYS', 365))

    # Surveillance Certificate Transparency (crt.sh) : detection des certificats
    # emis pour les domaines suivis a l'insu de la DSI. Desactivable globalement.
    CT_MONITORING = os.getenv('CT_MONITORING', 'true').lower() in ('true', '1', 'yes')

    # Tableau de bord personnalisable (chaque utilisateur choisit et ordonne ses
    # blocs). Desactivable globalement -> disposition par defaut pour tous.
    DASHBOARD_CUSTOM = os.getenv('DASHBOARD_CUSTOM', 'true').lower() in ('true', '1', 'yes')

    MAIL_METHOD = os.getenv('MAIL_METHOD', 'smtp')

    MAIL_SERVER = os.getenv('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() in ('true', '1', 'yes')
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@localhost')

    O365_CLIENT_ID = os.getenv('O365_CLIENT_ID', '')
    O365_CLIENT_SECRET = os.getenv('O365_CLIENT_SECRET', '')
    O365_TENANT_ID = os.getenv('O365_TENANT_ID', '')
    O365_SENDER_EMAIL = os.getenv('O365_SENDER_EMAIL', '')
    O365_REDIRECT_URI = os.getenv('O365_REDIRECT_URI', 'http://127.0.0.1:5000/auth/o365/callback')

    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
    ALERT_RECIPIENTS = os.getenv('ALERT_RECIPIENTS', '').split(',')

    # Envoi planifie du bilan PDF : off / weekly (lundi) / monthly (le 1er).
    # Destinataires dedies, repli sur ALERT_RECIPIENTS si vide.
    REPORT_SCHEDULE = os.getenv('REPORT_SCHEDULE', 'off')
    REPORT_RECIPIENTS = [r for r in os.getenv('REPORT_RECIPIENTS', '').split(',') if r.strip()]

    # Anti-bruteforce du login : nombre d'echecs avant blocage temporaire.
    LOGIN_MAX_ATTEMPTS = int(os.getenv('LOGIN_MAX_ATTEMPTS', 5))
    LOGIN_LOCKOUT_MINUTES = int(os.getenv('LOGIN_LOCKOUT_MINUTES', 15))

    # Si actif, un administrateur sans 2FA est contraint d'en activer une avant
    # d'acceder au reste de l'application (la section qui centralise l'etat du SI
    # justifie une authentification forte des comptes a privileges).
    REQUIRE_2FA_ADMIN = os.getenv('REQUIRE_2FA_ADMIN', 'false').lower() in ('true', '1', 'yes')

    APP_HOST = os.getenv('APP_HOST', '127.0.0.1')
    APP_PORT = int(os.getenv('APP_PORT', 5000))
    APP_DEBUG = os.getenv('APP_DEBUG', 'false').lower() in ('true', '1', 'yes')

    # URL publique de l'application, utilisee pour les liens dans les emails.
    APP_BASE_URL = os.getenv('APP_BASE_URL', f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', 5000)}")

    # Notifications par webhook (optionnel, en plus du mail) : Teams / Slack / Discord.
    TEAMS_WEBHOOK_URL = os.getenv('TEAMS_WEBHOOK_URL', '')
    SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

    # Jeton secret pour l'ingestion des mails recap de backup (POST /backups/ingest).
    # Laisser vide pour desactiver le point d'entree.
    BACKUP_INGEST_TOKEN = os.getenv('BACKUP_INGEST_TOKEN', '')

    # Integration Sesame : API GET /api/assets protegee par cle (Authorization:
    # Bearer). Gere depuis les Preferences (cle chiffree en base). Repli .env.
    SESAME_API_ENABLED = os.getenv('SESAME_API_ENABLED', 'false').lower() in ('true', '1', 'yes')
    SESAME_API_TOKEN = os.getenv('SESAME_API_TOKEN', '')

    # Repertoire ou sont deposes les mails recap de backup (.eml/.txt/.html).
    # Sentinelle le scanne automatiquement. Laisser vide pour desactiver.
    BACKUP_INBOX_DIR = os.getenv('BACKUP_INBOX_DIR', '')

    # Auto-sauvegarde de la base SQLite de Sentinelle.
    # Repertoire (vide = <instance>/db_backups) et nombre de copies conservees.
    BACKUP_DB_DIR = os.getenv('BACKUP_DB_DIR', '')
    BACKUP_DB_KEEP = int(os.getenv('BACKUP_DB_KEEP', 14))
