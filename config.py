import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///admin_dashboard.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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

    APP_HOST = os.getenv('APP_HOST', '127.0.0.1')
    APP_PORT = int(os.getenv('APP_PORT', 5000))
    APP_DEBUG = os.getenv('APP_DEBUG', 'false').lower() in ('true', '1', 'yes')

    # URL publique de l'application, utilisee pour les liens dans les emails.
    APP_BASE_URL = os.getenv('APP_BASE_URL', f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', 5000)}")

    # Jeton secret pour l'ingestion des mails recap de backup (POST /backups/ingest).
    # Laisser vide pour desactiver le point d'entree.
    BACKUP_INGEST_TOKEN = os.getenv('BACKUP_INGEST_TOKEN', '')
