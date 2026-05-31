import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


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

    # Longueur minimale des mots de passe.
    PASSWORD_MIN_LENGTH = int(os.getenv('PASSWORD_MIN_LENGTH', 8))

    # Authentification LDAP / Active Directory (cohabite avec le compte local).
    LDAP_ENABLED = os.getenv('LDAP_ENABLED', 'false').lower() in ('true', '1', 'yes')
    LDAP_SERVER = os.getenv('LDAP_SERVER', '')          # ex: ldap://dc.chatillon.lan
    LDAP_PORT = int(os.getenv('LDAP_PORT', 389))
    LDAP_USE_SSL = os.getenv('LDAP_USE_SSL', 'false').lower() in ('true', '1', 'yes')
    LDAP_DOMAIN = os.getenv('LDAP_DOMAIN', '')           # ex: chatillon.lan (pour le bind UPN)
    LDAP_BASE_DN = os.getenv('LDAP_BASE_DN', '')         # ex: DC=chatillon,DC=lan (recherche email)
    LDAP_USER_DN_TEMPLATE = os.getenv('LDAP_USER_DN_TEMPLATE', '')  # alternative au bind UPN
    LDAP_DEFAULT_ROLE = os.getenv('LDAP_DEFAULT_ROLE', 'viewer')    # role des comptes AD provisionnes
    # Compte de service pour la synchro d'expiration des mots de passe AD (lecture seule).
    LDAP_BIND_USER = os.getenv('LDAP_BIND_USER', '')        # ex: svc-sentinelle@chatillon.lan
    LDAP_BIND_PASSWORD = os.getenv('LDAP_BIND_PASSWORD', '')

    # Seuils de statut en jours restants : (danger <=, attention <=, proche <=).
    THRESHOLD_EXPIRY = _triplet('THRESHOLD_EXPIRY', (7, 15, 30))   # comptes, certificats
    THRESHOLD_DOMAIN = _triplet('THRESHOLD_DOMAIN', (30, 60, 90))  # noms de domaine
    THRESHOLD_TASK = _triplet('THRESHOLD_TASK', (7, 15, 30))       # tests, revues de droits

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

    # Anti-bruteforce du login : nombre d'echecs avant blocage temporaire.
    LOGIN_MAX_ATTEMPTS = int(os.getenv('LOGIN_MAX_ATTEMPTS', 5))
    LOGIN_LOCKOUT_MINUTES = int(os.getenv('LOGIN_LOCKOUT_MINUTES', 15))

    APP_HOST = os.getenv('APP_HOST', '127.0.0.1')
    APP_PORT = int(os.getenv('APP_PORT', 5000))
    APP_DEBUG = os.getenv('APP_DEBUG', 'false').lower() in ('true', '1', 'yes')

    # URL publique de l'application, utilisee pour les liens dans les emails.
    APP_BASE_URL = os.getenv('APP_BASE_URL', f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', 5000)}")

    # Jeton secret pour l'ingestion des mails recap de backup (POST /backups/ingest).
    # Laisser vide pour desactiver le point d'entree.
    BACKUP_INGEST_TOKEN = os.getenv('BACKUP_INGEST_TOKEN', '')

    # Repertoire ou sont deposes les mails recap de backup (.eml/.txt/.html).
    # Sentinelle le scanne automatiquement. Laisser vide pour desactiver.
    BACKUP_INBOX_DIR = os.getenv('BACKUP_INBOX_DIR', '')

    # Auto-sauvegarde de la base SQLite de Sentinelle.
    # Repertoire (vide = <instance>/db_backups) et nombre de copies conservees.
    BACKUP_DB_DIR = os.getenv('BACKUP_DB_DIR', '')
    BACKUP_DB_KEEP = int(os.getenv('BACKUP_DB_KEEP', 14))
