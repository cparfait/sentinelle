from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db


# Seuils par defaut (danger, warning, info) en jours restants. SOURCE UNIQUE
# referencee a la fois par les modeles et par le scheduler : evite des valeurs
# par defaut divergentes entre la couleur du tableau de bord et le declenchement
# des alertes. La config (.env / Preferences) reste prioritaire si definie.
DEFAULT_THRESHOLDS = {
    'THRESHOLD_EXPIRY': (7, 15, 30),     # comptes, certificats
    'THRESHOLD_DOMAIN': (30, 60, 90),    # noms de domaine
    'THRESHOLD_TASK': (7, 15, 30),       # tests, revues de droits
    'THRESHOLD_CONTRACT': (60, 90, 180),  # contrats / licences
    'THRESHOLD_WARRANTY': (30, 60, 90),  # fin de garantie (inventaire)
}


def _thresholds(key, default=None):
    """Seuils (danger, warning, info) en jours, depuis la config si disponible,
    sinon depuis DEFAULT_THRESHOLDS."""
    if default is None:
        default = DEFAULT_THRESHOLDS.get(key)
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except Exception:
        return default


def threshold_for(key):
    """Seuils effectifs d'une categorie (config sinon defaut). Utilise par le
    scheduler pour partager exactement la meme politique que les modeles."""
    return _thresholds(key)


def _status_from_days(days_left, key, default=None):
    d, w, i = _thresholds(key, default)
    if days_left <= d:
        return 'danger'
    if days_left <= w:
        return 'warning'
    if days_left <= i:
        return 'info'
    return 'success'

# Categories soumises aux permissions par role (les sections Utilisateurs et
# Preferences restent reservees aux administrateurs via is_admin).
PERMISSION_CATEGORIES = ['accounts', 'certificates', 'domains', 'backups', 'tests',
                         'reviews', 'updates', 'inventory', 'contracts', 'alerts']
CATEGORY_LABELS = {
    'accounts': 'Comptes', 'certificates': 'Certificats', 'domains': 'Domaines',
    'backups': 'Backups', 'tests': 'Tests', 'reviews': 'Revue de droits',
    'updates': 'Mises à jour', 'inventory': 'Inventaire',
    'contracts': 'Contrats & fournisseurs', 'alerts': 'Alertes',
}
# Niveaux : 0 aucun, 1 lecture, 2 ecriture, 3 suppression (cumulatifs)
PERMISSION_LEVELS = {0: 'Aucun', 1: 'Lecture', 2: 'Écriture', 3: 'Suppression'}

# Categories agregees dans l'indicateur « Conformite globale » du tableau de bord.
CONFORMITY_CATEGORIES = ['accounts', 'certificates', 'domains', 'backups',
                         'tests', 'reviews', 'updates', 'inventory', 'contracts']


class Setting(db.Model):
    """Reglages applicatifs simples (cle/valeur texte). Peu d'entrees."""
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)


class EolCache(db.Model):
    """Cache local des donnees End-of-Life recuperees depuis endoflife.date
    (un enregistrement par produit, payload JSON). Rafraichi hors ligne."""
    product = db.Column(db.String(64), primary_key=True)
    payload = db.Column(db.Text)   # JSON brut des cycles
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AppConfig(db.Model):
    """Configuration applicative persistee en base (messagerie, LDAP, seuils,
    webhooks...). Remplace l'ancien stockage .env pour ces reglages. Les valeurs
    sensibles (mots de passe, secrets) sont chiffrees (cf. app/config_store.py)."""
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)
    is_secret = db.Column(db.Boolean, default=False)


WEBHOOK_CHANNELS = {'teams': 'Microsoft Teams', 'slack': 'Slack', 'discord': 'Discord'}


class Webhook(db.Model):
    """Webhook de notification rattache a une categorie de gestion (ou 'all').
    Permet d'avoir plusieurs webhooks par categorie."""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, default='all')  # accounts, certificates... ou 'all'
    channel = db.Column(db.String(16), nullable=False)                  # teams / slack / discord
    url = db.Column(db.String(512), nullable=False)
    label = db.Column(db.String(128))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)
    description = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)  # acces total + sections admin
    permissions = db.Column(db.JSON, default=dict)   # {categorie: niveau 0-3}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    totp_secret = db.Column(db.String(32))  # secret 2FA TOTP (None = desactive)
    # Jeton d'abonnement au calendrier ICS (None = pas de lien actif). Permet a
    # Outlook/Thunderbird de recuperer /agenda.ics sans session.
    ics_token = db.Column(db.String(64), unique=True, index=True)
    # Origine du compte : 'local' (gere dans l'app) ou 'ldap' (provisionne via AD).
    auth_source = db.Column(db.String(10), default='local')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def has_2fa(self):
        return bool(self.totp_secret)

    @property
    def is_ldap(self):
        return self.auth_source == 'ldap'

    def _role_obj(self):
        # perm_level() est appele des dizaines de fois par requete (menu,
        # boutons, can_view par categorie) : on memorise le Role sur flask.g
        # pour ne le charger qu'une fois par requete.
        if not self.role:
            return None
        try:
            from flask import g
            cache = g.setdefault('_role_cache', {})
        except RuntimeError:  # hors contexte applicatif
            return Role.query.filter_by(name=self.role).first()
        if self.role not in cache:
            cache[self.role] = Role.query.filter_by(name=self.role).first()
        return cache[self.role]

    @property
    def is_admin(self):
        r = self._role_obj()
        if r is not None:
            return bool(r.is_admin)
        return self.role == 'admin'

    def perm_level(self, category):
        """Niveau de droit (0-3) sur une categorie."""
        r = self._role_obj()
        if r is not None:
            if r.is_admin:
                return 3
            return int((r.permissions or {}).get(category, 0))
        # Repli si aucun enregistrement Role (compat heritee)
        if self.role == 'admin':
            return 3
        if self.role == 'editor':
            return 1 if category == 'alerts' else 3
        return 1  # viewer : lecture seule

    def can_view(self, category=None):
        if category is None:
            return True
        return self.perm_level(category) >= 1

    def can_edit(self, category=None):
        if category is None:
            return self.is_admin or any(
                self.perm_level(c) >= 2 for c in PERMISSION_CATEGORIES)
        return self.perm_level(category) >= 2

    def can_delete(self, category):
        return self.perm_level(category) >= 3

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(128), nullable=False)
    username = db.Column(db.String(128), nullable=False)
    url = db.Column(db.String(256))
    description = db.Column(db.Text)
    last_password_change = db.Column(db.Date)
    next_password_change = db.Column(db.Date)
    rotation_days = db.Column(db.Integer, default=90)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('AccountHistory', backref='account', lazy='dynamic', cascade='all, delete-orphan')

    def status(self):
        if not self.next_password_change:
            return 'warning'
        days_left = (self.next_password_change - datetime.now(timezone.utc).date()).days
        return _status_from_days(days_left, 'THRESHOLD_EXPIRY')


class AccountHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(128), nullable=False)
    domain = db.Column(db.String(256), nullable=False)
    issuer = db.Column(db.String(128))
    # Equipement de l'inventaire qui porte ce certificat (vue 360°), optionnel.
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    equipment = db.relationship('Equipment', backref=db.backref('certificates', lazy='dynamic'))
    issued_at = db.Column(db.Date)
    expiry_date = db.Column(db.Date, nullable=False)
    auto_renew = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('CertificateHistory', backref='certificate', lazy='dynamic', cascade='all, delete-orphan')

    def status(self):
        days_left = (self.expiry_date - datetime.now(timezone.utc).date()).days
        return _status_from_days(days_left, 'THRESHOLD_EXPIRY')


class CertificateHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificate.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Backup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(128), nullable=False)
    backup_type = db.Column(db.String(64))
    location = db.Column(db.String(256))
    # Equipement de l'inventaire sauvegarde par ce backup (vue 360°), optionnel.
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    equipment = db.relationship('Equipment', backref=db.backref('backups', lazy='dynamic'))
    frequency = db.Column(db.String(64))
    expected_time = db.Column(db.String(5))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    checks = db.relationship('BackupCheck', backref='backup', lazy='dynamic', cascade='all, delete-orphan')

    def today_check(self):
        # Memoise sur l'instance : computed_status() est appele plusieurs fois
        # par requete (badges, stats, urgences) et refaisait la requete a chaque fois.
        if not hasattr(self, '_today_check_memo'):
            today = datetime.now(timezone.utc).date()
            self._today_check_memo = self.checks.filter(
                db.func.date(BackupCheck.checked_at) == today
            ).first()
        return self._today_check_memo

    # Cadence attendue (jours) et tolerance avant alerte, selon la frequence.
    _FREQ_PERIOD = {'daily': 1, 'weekly': 7, 'monthly': 31}
    _FREQ_TOLERANCE = {'daily': 1, 'weekly': 2, 'monthly': 5}
    _FREQ_LABEL = {'daily': 'Quotidien', 'weekly': 'Hebdomadaire', 'monthly': 'Mensuel'}

    def frequency_label(self):
        return self._FREQ_LABEL.get(self.frequency, self.frequency or 'Non definie')

    def expected_interval_days(self):
        return self._FREQ_PERIOD.get(self.frequency, 1)

    def _tolerance_days(self):
        return self._FREQ_TOLERANCE.get(self.frequency, 1)

    def last_ok_check(self):
        if not hasattr(self, '_last_ok_memo'):
            self._last_ok_memo = self.checks.filter(BackupCheck.status == 'ok') \
                .order_by(BackupCheck.check_date.desc()).first()
        return self._last_ok_memo

    def days_since_last_ok(self):
        last_ok = self.last_ok_check()
        if not last_ok:
            return None
        return (datetime.now(timezone.utc).date() - last_ok.check_date).days

    def computed_status(self):
        """Statut tenant compte de la frequence : un backup hebdo/mensuel n'est
        pas en retard simplement parce qu'il n'a pas tourne aujourd'hui."""
        tc = self.today_check()
        if tc:
            if tc.status == 'failed':
                return 'danger'
            if tc.status == 'warning':
                return 'warning'
            if tc.status == 'ok':
                return 'success'

        days_since = self.days_since_last_ok()
        if days_since is None:
            # jamais de backup OK enregistre
            return 'warning' if self.checks.first() else 'info'

        period = self.expected_interval_days()
        tolerance = self._tolerance_days()
        if days_since <= period:
            return 'success'
        if days_since <= period + tolerance:
            return 'warning'
        return 'danger'

    def success_rate(self, days=30):
        """Taux de reussite base sur le PREMIER etat de chaque jour (incidents
        corriges ensuite restent comptes)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        checks = self.checks.filter(BackupCheck.checked_at >= since).all()
        total = len(checks)
        if total == 0:
            return None
        ok = sum(1 for c in checks if (c.first_status or c.status) == 'ok')
        return round((ok / total) * 100, 1)

    def streak(self):
        checks = self.checks.order_by(BackupCheck.check_date.desc()).limit(365).all()
        if not checks:
            return 0
        count = 0
        for c in checks:
            if (c.first_status or c.status) == 'ok':
                count += 1
            else:
                break
        return count


class BackupCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.Integer, db.ForeignKey('backup.id'), nullable=False, index=True)
    check_date = db.Column(db.Date, nullable=False, index=True)  # requete par date seule (tendances)
    status = db.Column(db.String(20), nullable=False, default='ok')
    # Premier etat constate ce jour-la (fige) : sert aux stats pour ne pas
    # masquer un incident corrige plus tard dans la journee.
    first_status = db.Column(db.String(20))
    comment = db.Column(db.Text)
    checked_by = db.Column(db.String(64))
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('backup_id', 'check_date', name='uq_backup_check_date'),)


class BackupHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.Integer, db.ForeignKey('backup.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    # Statut brut saisi (ok/warning/failed) pour les entrees action='check' :
    # permet d'afficher chaque statut du jour, meme s'il y en a plusieurs.
    status = db.Column(db.String(20))
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TestTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    test_type = db.Column(db.String(64), nullable=False)
    description = db.Column(db.Text)
    last_performed = db.Column(db.Date)
    next_due = db.Column(db.Date)
    frequency_days = db.Column(db.Integer, default=90)
    status = db.Column(db.String(20), default='pending')
    result = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('TestHistory', backref='test_task', lazy='dynamic', cascade='all, delete-orphan')

    def computed_status(self):
        if self.status == 'failed':
            return 'danger'
        if self.status == 'completed':
            return 'success'
        if not self.next_due:
            return 'warning'
        days_left = (self.next_due - datetime.now(timezone.utc).date()).days
        return _status_from_days(days_left, 'THRESHOLD_TASK')


class TestHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('test_task.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    result = db.Column(db.Text)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Domain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    registrar = db.Column(db.String(128))
    expiry_date = db.Column(db.Date)
    auto_renew = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Surveillance Certificate Transparency (crt.sh) : detecte les certificats
    # emis pour ce domaine a l'insu de la DSI. ct_last_id = plus grand identifiant
    # crt.sh deja vu (ligne de base au premier scan pour ne pas alerter l'historique).
    ct_enabled = db.Column(db.Boolean, default=True)
    ct_last_id = db.Column(db.BigInteger)
    histories = db.relationship('DomainHistory', backref='domain', lazy='dynamic', cascade='all, delete-orphan')
    ct_entries = db.relationship('CtLogEntry', backref='domain', lazy='dynamic', cascade='all, delete-orphan')

    def status(self):
        if not self.expiry_date:
            return 'warning'
        days_left = (self.expiry_date - datetime.now(timezone.utc).date()).days
        return _status_from_days(days_left, 'THRESHOLD_DOMAIN')

    def ct_new_count(self):
        return self.ct_entries.filter_by(status='new').count()


class DomainHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class CtLogEntry(db.Model):
    """Certificat observe dans les journaux de Certificate Transparency (crt.sh)
    pour un domaine surveille. Sert a reperer les certificats emis a l'insu de la
    DSI (shadow IT, prestataire, usurpation).

    Statuts : baseline (existant au 1er scan, silencieux) / new (nouveau, alerte) /
    acknowledged (verifie) / ignored."""
    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), nullable=False, index=True)
    crtsh_id = db.Column(db.BigInteger, index=True)      # identifiant crt.sh (dedup)
    serial_number = db.Column(db.String(128))
    common_name = db.Column(db.String(256))
    name_value = db.Column(db.Text)                      # SAN(s), un par ligne
    issuer_name = db.Column(db.String(256))
    not_before = db.Column(db.Date)
    not_after = db.Column(db.Date)
    entry_timestamp = db.Column(db.DateTime)             # date d'ajout au journal CT
    first_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(16), default='new')
    acknowledged_by = db.Column(db.String(64))
    acknowledged_at = db.Column(db.DateTime)

    __table_args__ = (db.UniqueConstraint('domain_id', 'crtsh_id',
                                          name='uq_ctlog_domain_crtsh'),)

    def sans(self):
        """Liste des noms (SAN) du certificat, dedupliquee et sans les *."""
        seen, out = set(), []
        for s in (self.name_value or '').splitlines():
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out


class AccessReview(db.Model):
    """Revue de droits d'une application metier (activite recurrente)."""
    id = db.Column(db.Integer, primary_key=True)
    application = db.Column(db.String(128), nullable=False)
    responsible = db.Column(db.String(128))
    scope = db.Column(db.Text)  # perimetre / description
    frequency_days = db.Column(db.Integer, default=365)
    last_review = db.Column(db.Date)
    next_review = db.Column(db.Date)
    status = db.Column(db.String(20), default='pending')  # pending / completed / failed
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('ReviewHistory', backref='review', lazy='dynamic', cascade='all, delete-orphan')

    def computed_status(self):
        if self.status == 'failed':
            return 'danger'
        if not self.next_review:
            return 'warning'
        days_left = (self.next_review - datetime.now(timezone.utc).date()).days
        return _status_from_days(days_left, 'THRESHOLD_TASK')


class ReviewHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('access_review.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SystemUpdate(db.Model):
    """Suivi des mises a jour d'une application ou d'un systeme (statut manuel)."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    system_type = db.Column(db.String(32), default='application')  # application / system
    current_version = db.Column(db.String(64))
    latest_version = db.Column(db.String(64))
    status = db.Column(db.String(20), default='up_to_date')  # up_to_date / update_available / critical
    # Equipement de l'inventaire qui heberge cette application (vue 360°), optionnel.
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    equipment = db.relationship('Equipment', backref=db.backref('system_updates', lazy='dynamic'))
    # Logiciel metier concerne par cette MAJ (inventaire Logiciels), optionnel.
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), index=True)
    last_update = db.Column(db.Date)
    updater_type = db.Column(db.String(20), default='interne')  # interne / prestataire
    updated_by = db.Column(db.String(128))  # nom de la personne ayant fait la MaJ
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('UpdateHistory', backref='system_update', lazy='dynamic', cascade='all, delete-orphan')

    def status_color(self):
        return {'up_to_date': 'success', 'update_available': 'warning',
                'critical': 'danger'}.get(self.status, 'info')


class UpdateHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    update_id = db.Column(db.Integer, db.ForeignKey('system_update.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


ASSET_TYPE_LABELS = {'application': 'Application', 'divers': 'Divers'}


class Asset(db.Model):
    """Catalogue d'applications et de systemes/serveurs, defini dans les
    preferences. Alimente les listes deroulantes des mises a jour et revues."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    asset_type = db.Column(db.String(20), default='application')  # application / divers
    description = db.Column(db.String(256))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def type_label(self):
        return ASSET_TYPE_LABELS.get(self.asset_type, self.asset_type)


EQUIPMENT_KIND_LABELS = {'vm': 'VM', 'physical': 'Serveur physique', 'nas': 'NAS'}
ENVIRONMENT_LABELS = {'prod': 'Production', 'preprod': 'Préproduction',
                      'dev': 'Développement', 'decommissioned': 'Décommissionné'}
CRITICALITY_LABELS = {1: '1 - Faible', 2: '2 - Modérée', 3: '3 - Élevée', 4: '4 - Vitale'}


class Equipment(db.Model):
    """Inventaire unifie : VM, serveurs physiques et NAS.
    Les champs specifiques a un type restent vides pour les autres."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), default='vm', nullable=False)  # vm / physical / nas
    name = db.Column(db.String(128), nullable=False)
    environment = db.Column(db.String(16))      # prod / preprod / dev
    criticality = db.Column(db.Integer)          # 1 a 4 (criticite cyber)

    # Systeme
    os = db.Column(db.String(128))
    os_version = db.Column(db.String(64))
    os_last_update = db.Column(db.Date)
    supervision = db.Column(db.String(128))      # outil de supervision (physique/nas)
    supervised = db.Column(db.Boolean, default=False)   # VM : supervision
    cyberwatch = db.Column(db.Boolean, default=False)   # VM : Cyberwatch
    ninja_one = db.Column(db.Boolean, default=False)    # VM : Ninja One

    # Reseau (VM / NAS)
    ip_address = db.Column(db.String(64))
    netmask = db.Column(db.String(64))
    vlan = db.Column(db.String(32))

    # Hote (VM)
    host_server = db.Column(db.String(128))
    hypervisor = db.Column(db.String(64))

    # Ressources (VM)
    vcpu = db.Column(db.Integer)
    ram_go = db.Column(db.Float)
    hdd1_go = db.Column(db.Float)
    hdd2_go = db.Column(db.Float)
    hdd3_go = db.Column(db.Float)

    # Materiel & garantie (physique / nas)
    manufacturer_model = db.Column(db.String(128))
    serial_number = db.Column(db.String(128))
    purchase_date = db.Column(db.Date)
    warranty_end = db.Column(db.Date)
    maintenance_contract = db.Column(db.String(128))
    # Fournisseur / support a contacter en cas d'incident (annuaire).
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    supplier = db.relationship('Supplier', backref=db.backref('equipments', lazy='dynamic'))

    # Stockage (NAS)
    protocols = db.Column(db.String(128))
    access = db.Column(db.Text)
    capacity_to = db.Column(db.Float)
    used_to = db.Column(db.Float)
    raid = db.Column(db.String(64))

    # Role & logiciels
    role_principal = db.Column(db.String(128))
    business_software = db.Column(db.Text)
    user_services = db.Column(db.Text)
    usage = db.Column(db.Text)                   # usage principal / donnees (NAS)

    # Continuite & securite
    pra_pca = db.Column(db.String(128))
    backup1 = db.Column(db.String(128))
    backup1_freq = db.Column(db.String(64))
    backup2 = db.Column(db.String(128))
    backup2_freq = db.Column(db.String(64))
    observations = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def kind_label(self):
        return EQUIPMENT_KIND_LABELS.get(self.kind, self.kind)

    def env_label(self):
        return ENVIRONMENT_LABELS.get(self.environment, self.environment or '')

    def warranty_days_left(self):
        if not self.warranty_end:
            return None
        return (self.warranty_end - datetime.now(timezone.utc).date()).days

    def warranty_status(self):
        if not self.warranty_end:
            return None
        return _status_from_days(self.warranty_days_left(), 'THRESHOLD_WARRANTY')

    def os_update_stale(self):
        """MAJ OS jamais renseignee ou trop ancienne (seuil configurable)."""
        from flask import current_app
        try:
            limit = int(current_app.config.get('OS_STALE_DAYS', 365))
        except Exception:
            limit = 365
        if not self.os and not self.os_last_update:
            return False
        if not self.os_last_update:
            return True
        return (datetime.now(timezone.utc).date() - self.os_last_update).days > limit

    def missing_backup(self):
        """Criticite elevee sans aucune sauvegarde connue : ni champ texte
        renseigne, ni backup de la section Backups lie a cet equipement."""
        if (self.criticality or 0) < 3:
            return False
        if self.backup1 or self.backup2:
            return False
        return self.backups.filter_by(is_active=True).first() is None

    def linked_items(self):
        """Elements des autres modules rattaches a cet equipement (vue 360°)."""
        return {
            'certificates': self.certificates.filter_by(is_active=True)
                .order_by(Certificate.expiry_date.asc()).all(),
            'backups': self.backups.filter_by(is_active=True)
                .order_by(Backup.service_name).all(),
            'updates': self.system_updates.filter_by(is_active=True)
                .order_by(SystemUpdate.name).all(),
            'contracts': self.contracts.filter_by(is_active=True)
                .order_by(Contract.end_date.asc()).all(),
        }

    def eol_info(self):
        """Infos End-of-Life de l'OS (via cache endoflife.date), ou None si non
        reconnu. Voir app/eol.py. N'effectue aucun appel reseau."""
        from app import eol
        return eol.lookup(self.os, self.os_version)

    def computed_status(self):
        found = set()
        ws = self.warranty_status()
        if ws:
            found.add(ws)
        if self.missing_backup():
            found.add('danger')
        if self.os_update_stale():
            found.add('warning')
        ei = self.eol_info()
        if ei and ei.get('status'):
            found.add(ei['status'])
        for s in ('danger', 'warning', 'info', 'success'):
            if s in found:
                return s
        return 'success'

    def status_reasons(self):
        """Liste lisible des points d'attention (pour fiche et alertes)."""
        out = []
        d = self.warranty_days_left()
        if d is not None and d <= 90:
            out.append(('Garantie expirée' if d < 0 else f'Garantie expire dans {d} j'))
        if self.missing_backup():
            out.append('Criticité élevée sans sauvegarde')
        if self.os_update_stale():
            out.append('MAJ OS absente ou trop ancienne')
        ei = self.eol_info()
        if ei and ei.get('status') in ('danger', 'warning'):
            dt = ei.get('eol_date')
            if dt and ei.get('days_left') is not None and ei['days_left'] < 0:
                out.append(f"OS en fin de support depuis le {dt.strftime('%d/%m/%Y')}")
            elif dt:
                out.append(f"OS en fin de support le {dt.strftime('%d/%m/%Y')}")
            else:
                out.append("OS en fin de support")
        return out


SUPPLIER_KIND_LABELS = {'editor': 'Éditeur logiciel', 'manufacturer': 'Constructeur',
                        'provider': 'Prestataire', 'operator': 'Opérateur', 'other': 'Autre'}


class Supplier(db.Model):
    """Annuaire fournisseurs / prestataires : qui appeler en cas d'incident
    (hotline, n° client, portail support)."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    kind = db.Column(db.String(32), default='provider')  # cf. SUPPLIER_KIND_LABELS
    contact_name = db.Column(db.String(128))   # interlocuteur habituel
    phone = db.Column(db.String(64))           # standard / commercial
    support_phone = db.Column(db.String(64))   # hotline support
    email = db.Column(db.String(128))
    support_url = db.Column(db.String(256))    # portail de tickets
    customer_ref = db.Column(db.String(128))   # n° client / identifiant support
    hours = db.Column(db.String(128))          # horaires du support (ex. 8h-18h, J+1...)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def kind_label(self):
        return SUPPLIER_KIND_LABELS.get(self.kind, self.kind or '')


CONTRACT_KIND_LABELS = {'maintenance': 'Maintenance', 'licence': 'Licence',
                        'subscription': 'Abonnement', 'market': 'Marché public',
                        'other': 'Autre'}


# Equipements couverts par un contrat (relation N:N). Premiere table
# d'association du projet ; alimentee au demarrage depuis l'ancien equipment_id.
contract_equipment = db.Table(
    'contract_equipment',
    db.Column('contract_id', db.Integer, db.ForeignKey('contract.id'), primary_key=True),
    db.Column('equipment_id', db.Integer, db.ForeignKey('equipment.id'), primary_key=True),
)


class Contract(db.Model):
    """Contrat, licence ou abonnement avec echeance et preavis de resiliation.
    La date qui compte pour agir est end_date - notice_days : au-dela, on subit
    la tacite reconduction ou la coupure du service."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    kind = db.Column(db.String(32), default='maintenance')  # cf. CONTRACT_KIND_LABELS
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    supplier = db.relationship('Supplier', backref=db.backref('contracts', lazy='dynamic'))
    reference = db.Column(db.String(128))      # n° de contrat / de marche
    cost_yearly = db.Column(db.Float)          # cout annuel TTC indicatif
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)              # echeance du contrat
    notice_days = db.Column(db.Integer, default=0)   # preavis de resiliation (jours)
    auto_renew = db.Column(db.Boolean, default=False)  # tacite reconduction
    # Colonne historique (1 equipement) conservee pour la migration : SQLite ne
    # permet pas de la retirer proprement. Les liens font foi via `equipments`.
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    # Plusieurs equipements couverts par le contrat (M:N). Cote contrat = liste
    # simple (affectation possible sur un contrat neuf) ; le backref
    # `Equipment.contracts` reste dynamique pour la vue 360° (filter_by).
    equipments = db.relationship('Equipment', secondary=contract_equipment,
                                 backref=db.backref('contracts', lazy='dynamic'))
    responsible = db.Column(db.String(128))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('ContractHistory', backref='contract', lazy='dynamic',
                                cascade='all, delete-orphan')

    def kind_label(self):
        return CONTRACT_KIND_LABELS.get(self.kind, self.kind or '')

    def action_deadline(self):
        """Date limite pour agir : echeance moins le preavis de resiliation."""
        if not self.end_date:
            return None
        return self.end_date - timedelta(days=self.notice_days or 0)

    def days_left(self):
        """Jours restants avant la date limite d'action (negatif = depassee)."""
        deadline = self.action_deadline()
        if deadline is None:
            return None
        return (deadline - datetime.now(timezone.utc).date()).days

    def status(self):
        days = self.days_left()
        if days is None:
            return 'warning'  # echeance non renseignee : a completer
        return _status_from_days(days, 'THRESHOLD_CONTRACT')


class ContractHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False, index=True)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# Serveur(s) sur lesquels un logiciel est installe (relation N:N).
software_equipment = db.Table(
    'software_equipment',
    db.Column('software_id', db.Integer, db.ForeignKey('software.id'), primary_key=True),
    db.Column('equipment_id', db.Integer, db.ForeignKey('equipment.id'), primary_key=True),
)


class Software(db.Model):
    """Logiciel metier inventorie : editeur (fournisseur), serveur(s)
    d'installation, hebergement SaaS, contrat et suivi des mises a jour.
    Remplace l'ancien « catalogue applications » des Preferences."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)  # editeur/fournisseur
    supplier = db.relationship('Supplier', backref=db.backref('software', lazy='dynamic'))
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), index=True)
    contract = db.relationship('Contract', backref=db.backref('software', lazy='dynamic'))
    version = db.Column(db.String(64))
    is_saas = db.Column(db.Boolean, default=False)  # heberge hors parc (Cloud)
    url = db.Column(db.String(256))
    criticality = db.Column(db.Integer)             # 1-4
    responsible = db.Column(db.String(128))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    # Serveur(s) d'installation (M:N). Backref Equipment.software_list.
    equipments = db.relationship('Equipment', secondary=software_equipment,
                                 backref=db.backref('software_list', lazy='dynamic'))
    # Mises a jour rattachees (via SystemUpdate.software_id) : backref .software.
    system_updates = db.relationship('SystemUpdate', backref='software', lazy='dynamic')

    def computed_status(self):
        """Statut agrege sur les MAJ liees : rouge si critique, orange si une
        MAJ est disponible, vert sinon."""
        updates = self.system_updates.filter_by(is_active=True).all()
        if any(u.status == 'critical' for u in updates):
            return 'danger'
        if any(u.status == 'update_available' for u in updates):
            return 'warning'
        return 'success'


class SchedulerRun(db.Model):
    """Trace d'execution d'un job planifie (diagnostic des alertes)."""
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(64))
    status = db.Column(db.String(20))  # ok / error
    message = db.Column(db.Text)
    run_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ActionLog(db.Model):
    """Journal d'actions central et persistant (survit a la suppression des
    entites) : qui a fait quoi, et quand."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64))
    action = db.Column(db.String(64), nullable=False)
    category = db.Column(db.String(64))
    detail = db.Column(db.Text)
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class LoginThrottle(db.Model):
    """Suivi des echecs de connexion par couple (identifiant, IP source) :
    anti-bruteforce sans permettre a un tiers de verrouiller le compte d'un
    collegue depuis une autre adresse (deni de service cible)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, index=True)
    ip = db.Column(db.String(64), nullable=False, default='', index=True)
    failed_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('username', 'ip', name='uq_throttle_user_ip'),)


class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(64))
    entity_id = db.Column(db.Integer)
    entity_name = db.Column(db.String(128))
    message = db.Column(db.Text)
    recipients = db.Column(db.String(512))
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    status = db.Column(db.String(20), default='sent')
    # Anti-doublon et rattrapage cherchent la derniere alerte d'une entite,
    # triee par sent_at : l'index couvre exactement cette requete.
    # (L'ancien ix_alert_log_entity (entity_type, entity_id) devient redondant ;
    # sa suppression dans les bases existantes reste manuelle.)
    __table_args__ = (db.Index('ix_alert_log_entity_sent',
                               'entity_type', 'entity_id', 'sent_at'),)


class AlertSnooze(db.Model):
    """Report d'alerte : suspend les notifications d'un element jusqu'a une date.
    Table dediee -> pas de colonne ajoutee aux modeles existants."""
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(64), nullable=False)  # account/certificate/backup/test
    entity_id = db.Column(db.Integer, nullable=False)
    snoozed_until = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    created_by = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('entity_type', 'entity_id',
                                          name='uq_snooze_entity'),)
