"""Configuration applicative persistee en base (table AppConfig).

Remplace l'ancien stockage .env pour les reglages modifiables via la page
Preferences (messagerie, LDAP/AD, seuils, destinataires, webhooks globaux).

- Le `.env` ne sert plus que pour l'amorcage (SECRET_KEY, URL de la base,
  hote/port/debug) et la migration initiale.
- Les valeurs sensibles (mots de passe, secrets) sont chiffrees (Fernet, cle
  derivee de SECRET_KEY). Ainsi, meme si le fichier .db est exporte/sauvegarde,
  les secrets restent illisibles sans la SECRET_KEY (qui, elle, reste hors base).
"""
import base64
import hashlib
import logging

from app import db

logger = logging.getLogger(__name__)

# Cles dont la valeur est un secret -> chiffree en base.
SECRET_KEYS = {'MAIL_PASSWORD', 'O365_CLIENT_SECRET', 'LDAP_BIND_PASSWORD',
               'SESAME_API_TOKEN'}

# Typage applique au chargement (le reste = chaine).
_BOOL = {'LDAP_ENABLED', 'LDAP_USE_SSL', 'LDAP_VALIDATE_CERT', 'CT_MONITORING',
         'SESAME_API_ENABLED', 'DASHBOARD_CUSTOM'}
_INT = {'LDAP_PORT', 'MAIL_PORT'}
_TRIPLET = {'THRESHOLD_EXPIRY', 'THRESHOLD_DOMAIN', 'THRESHOLD_TASK', 'THRESHOLD_CONTRACT'}

# Destinataires : liste globale + une liste optionnelle par categorie d'entite
# (vide = repli sur la globale). Cles alignees sur les entity_type des alertes.
ALERT_CATEGORIES = ('account', 'certificate', 'domain', 'backup', 'test',
                    'review', 'update', 'equipment', 'contract')
ALERT_CATEGORY_LABELS = {
    'account': 'Comptes / mots de passe', 'certificate': 'Certificats',
    'domain': 'Domaines', 'backup': 'Backups', 'test': 'Tests récurrents',
    'review': 'Revues de droits', 'update': 'Mises à jour',
    'equipment': 'Inventaire', 'contract': 'Contrats & licences',
}
_CSV = {'ALERT_RECIPIENTS', 'REPORT_RECIPIENTS'} | {
    f'ALERT_RECIPIENTS_{c.upper()}' for c in ALERT_CATEGORIES}

# Ensemble des cles gerees en base (= celles ecrites par la page Preferences).
MANAGED = _BOOL | _INT | _TRIPLET | _CSV | {
    'MAIL_METHOD', 'MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER',
    'O365_CLIENT_ID', 'O365_CLIENT_SECRET', 'O365_TENANT_ID', 'O365_SENDER_EMAIL', 'O365_REDIRECT_URI',
    'LDAP_SERVER', 'LDAP_CA_CERT', 'LDAP_DOMAIN', 'LDAP_BASE_DN', 'LDAP_REQUIRED_GROUP',
    'LDAP_DEFAULT_ROLE', 'LDAP_BIND_USER', 'LDAP_BIND_PASSWORD',
    'TEAMS_WEBHOOK_URL', 'SLACK_WEBHOOK_URL', 'DISCORD_WEBHOOK_URL',
    'REPORT_SCHEDULE',  # envoi planifie du bilan PDF : off / monthly / weekly
    'CT_MONITORING',    # surveillance Certificate Transparency (crt.sh) : on/off
    'DASHBOARD_CUSTOM', # tableau de bord personnalisable par utilisateur : on/off
    'SESAME_API_ENABLED', 'SESAME_API_TOKEN',  # integration Sesame (API + cle)
}


def _fernet():
    from cryptography.fernet import Fernet
    from flask import current_app
    secret = (current_app.config.get('SECRET_KEY') or 'dev-secret-key').encode('utf-8')
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _encrypt(value):
    try:
        return _fernet().encrypt((value or '').encode('utf-8')).decode('ascii')
    except Exception as e:
        logger.warning('Chiffrement config echoue : %s', e)
        return value or ''


def _decrypt(token):
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except Exception as e:
        logger.warning('Dechiffrement config echoue (SECRET_KEY changee ?) : %s', e)
        return ''


def _cast(key, raw):
    """Convertit la chaine stockee vers le type attendu par app.config."""
    if raw is None:
        raw = ''
    if key in _BOOL:
        return str(raw).lower() in ('true', '1', 'yes', 'on')
    if key in _INT:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if key in _TRIPLET:
        try:
            parts = [int(x.strip()) for x in str(raw).split(',') if x.strip()]
            if len(parts) == 3:
                return tuple(parts)
        except ValueError:
            pass
        return None
    if key in _CSV:
        return [p.strip() for p in str(raw).split(',') if p.strip()]
    return raw


def _serialize(key, value):
    """Convertit une valeur app.config vers la chaine a stocker."""
    if key in _BOOL:
        return 'true' if value else 'false'
    if key in _TRIPLET:
        return ','.join(str(x) for x in (value or ()))
    if key in _CSV:
        return ','.join(value or [])
    if value is None:
        return ''
    return str(value)


def save(updates):
    """Persiste un dict {CLE: valeur-chaine} en base (chiffre les secrets) et
    met a jour la config en memoire. Remplace l'ancien _update_env_file()."""
    from app.models import AppConfig
    from flask import current_app
    for key, val in updates.items():
        val = '' if val is None else str(val)
        secret = key in SECRET_KEYS
        stored = _encrypt(val) if secret else val
        row = db.session.get(AppConfig, key)
        if row is None:
            row = AppConfig(key=key)
            db.session.add(row)
        row.value = stored
        row.is_secret = secret
        # Reflet immediat en memoire (type correct).
        if key in MANAGED:
            current_app.config[key] = _cast(key, val)
    db.session.commit()


def load(app):
    """Applique les reglages stockes en base dans app.config (au demarrage)."""
    from app.models import AppConfig
    for row in AppConfig.query.all():
        if row.key not in MANAGED:
            continue
        raw = _decrypt(row.value) if row.is_secret else (row.value or '')
        app.config[row.key] = _cast(row.key, raw)


def seed_from_env(app):
    """Migration initiale : si la table est vide, on y copie les valeurs
    actuelles (issues du .env/defauts) pour ne rien perdre."""
    from app.models import AppConfig
    if db.session.query(AppConfig.key).first() is not None:
        return  # deja initialisee
    for key in MANAGED:
        val = app.config.get(key)
        secret = key in SECRET_KEYS
        stored = _encrypt(_serialize(key, val)) if secret else _serialize(key, val)
        db.session.add(AppConfig(key=key, value=stored, is_secret=secret))
    db.session.commit()
    app.logger.info('Configuration applicative initialisee en base (%d cles)', len(MANAGED))
