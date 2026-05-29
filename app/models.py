from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def is_admin(self):
        return self.role == 'admin'

    def can_edit(self):
        return self.role in ('admin', 'editor')

    def can_view(self, section=None):
        if self.role == 'admin':
            return True
        if not section:
            return True
        return True

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

    def computed_status(self):
        tc = self.today_check()
        if tc:
            if tc.status == 'ok':
                return 'success'
            elif tc.status == 'failed':
                return 'danger'
            elif tc.status == 'warning':
                return 'warning'
        today = datetime.now(timezone.utc).date()
        last_check = self.checks.order_by(BackupCheck.checked_at.desc()).first()
        if last_check:
            days_since = (today - last_check.checked_at.date()).days
            if days_since >= 2:
                return 'danger'
            elif days_since == 1:
                return 'warning'
        else:
            return 'info'
        return 'warning'

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
