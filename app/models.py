from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db

# Categories soumises aux permissions par role (les sections Utilisateurs et
# Preferences restent reservees aux administrateurs via is_admin).
PERMISSION_CATEGORIES = ['accounts', 'certificates', 'domains', 'backups', 'tests',
                         'reviews', 'updates', 'alerts']
CATEGORY_LABELS = {
    'accounts': 'Comptes', 'certificates': 'Certificats', 'domains': 'Domaines',
    'backups': 'Backups', 'tests': 'Tests', 'reviews': 'Revue de droits',
    'updates': 'Mises à jour', 'alerts': 'Alertes',
}
# Niveaux : 0 aucun, 1 lecture, 2 ecriture, 3 suppression (cumulatifs)
PERMISSION_LEVELS = {0: 'Aucun', 1: 'Lecture', 2: 'Écriture', 3: 'Suppression'}


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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def _role_obj(self):
        return Role.query.filter_by(name=self.role).first() if self.role else None

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
        today = datetime.now(timezone.utc).date()
        days_left = (self.next_password_change - today).days
        if days_left < 0:
            return 'danger'
        elif days_left <= 7:
            return 'danger'
        elif days_left <= 15:
            return 'warning'
        elif days_left <= 30:
            return 'info'
        return 'success'


class AccountHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(128), nullable=False)
    domain = db.Column(db.String(256), nullable=False)
    issuer = db.Column(db.String(128))
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
        today = datetime.now(timezone.utc).date()
        days_left = (self.expiry_date - today).days
        if days_left < 0:
            return 'danger'
        elif days_left <= 7:
            return 'danger'
        elif days_left <= 15:
            return 'warning'
        elif days_left <= 30:
            return 'info'
        return 'success'


class CertificateHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificate.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Backup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_name = db.Column(db.String(128), nullable=False)
    backup_type = db.Column(db.String(64))
    location = db.Column(db.String(256))
    frequency = db.Column(db.String(64))
    expected_time = db.Column(db.String(5))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    checks = db.relationship('BackupCheck', backref='backup', lazy='dynamic', cascade='all, delete-orphan')

    def today_check(self):
        today = datetime.now(timezone.utc).date()
        return self.checks.filter(
            db.func.date(BackupCheck.checked_at) == today
        ).first()

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
        return self.checks.filter(BackupCheck.status == 'ok') \
            .order_by(BackupCheck.check_date.desc()).first()

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
        from sqlalchemy import func
        since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)
        total = self.checks.filter(BackupCheck.checked_at >= since).count()
        if total == 0:
            return None
        ok = self.checks.filter(BackupCheck.checked_at >= since, BackupCheck.status == 'ok').count()
        return round((ok / total) * 100, 1)

    def streak(self):
        checks = self.checks.order_by(BackupCheck.checked_at.desc()).limit(365).all()
        if not checks:
            return 0
        count = 0
        for c in checks:
            if c.status == 'ok':
                count += 1
            else:
                break
        return count


class BackupCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.Integer, db.ForeignKey('backup.id'), nullable=False)
    check_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ok')
    comment = db.Column(db.Text)
    checked_by = db.Column(db.String(64))
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('backup_id', 'check_date', name='uq_backup_check_date'),)


class BackupHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.Integer, db.ForeignKey('backup.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
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
        today = datetime.now(timezone.utc).date()
        days_left = (self.next_due - today).days
        if days_left < 0:
            return 'danger'
        elif days_left <= 7:
            return 'danger'
        elif days_left <= 15:
            return 'warning'
        elif days_left <= 30:
            return 'info'
        return 'success'


class TestHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('test_task.id'), nullable=False)
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
    histories = db.relationship('DomainHistory', backref='domain', lazy='dynamic', cascade='all, delete-orphan')

    def status(self):
        if not self.expiry_date:
            return 'warning'
        days_left = (self.expiry_date - datetime.now(timezone.utc).date()).days
        if days_left < 0:
            return 'danger'
        elif days_left <= 30:
            return 'danger'
        elif days_left <= 60:
            return 'warning'
        elif days_left <= 90:
            return 'info'
        return 'success'


class DomainHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domain.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


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
        if days_left <= 7:
            return 'danger'
        if days_left <= 15:
            return 'warning'
        if days_left <= 30:
            return 'info'
        return 'success'


class ReviewHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('access_review.id'), nullable=False)
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
    update_id = db.Column(db.Integer, db.ForeignKey('system_update.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    comment = db.Column(db.Text)
    performed_by = db.Column(db.String(64))
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ActionLog(db.Model):
    """Journal d'actions central et persistant (survit a la suppression des
    entites) : qui a fait quoi, et quand."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64))
    action = db.Column(db.String(64), nullable=False)
    category = db.Column(db.String(64))
    detail = db.Column(db.Text)
    performed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class LoginThrottle(db.Model):
    """Suivi des echecs de connexion par identifiant (anti-bruteforce)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    failed_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(64))
    entity_id = db.Column(db.Integer)
    entity_name = db.Column(db.String(128))
    message = db.Column(db.Text)
    recipients = db.Column(db.String(512))
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), default='sent')


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
