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
    'backups': 'Sauvegardes', 'tests': 'Tests', 'reviews': 'Revues de droits',
    'updates': 'Mises à jour', 'inventory': 'Matériel & logiciels',
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
    # Personnalisation du tableau de bord (par utilisateur) : JSON
    # {"order": [cles visibles ordonnees], "hidden": [cles masquees]}.
    # None = disposition par defaut. Tolere l'ajout/retrait de blocs (voir
    # app.dashboard.resolve_dashboard_layout).
    dashboard_prefs = db.Column(db.Text)
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


# Ce qu'EST le certificat. Deux natures, une seule table : l'une et l'autre
# portent une echeance a surveiller, se renouvellent et se remplacent -- ce sont
# exactement les memes alertes, le meme agenda, le meme tableau de bord. En
# faire deux modules aurait double tout cela pour un seul mot qui change.
CERT_KIND_LABELS = {'tls': 'Certificat TLS', 'signature': 'Certificat électronique'}

CIVILITY_LABELS = {'m': 'M.', 'mme': 'Mme'}
# La civilite est A PART du nom, et non collee devant : « Mme ARNAUD » se
# rangerait sous M, avec les autres, et ni le tri ni la recherche ne seraient
# justes. NULLE pour un certificat de machine -- lui en inventer une serait
# pire que de la laisser vide.
CERT_USAGE_LABELS = {'signature': 'Signature', 'authentification': 'Authentification',
                     'cachet': 'Cachet serveur', 'autre': 'Autre'}
# Ce qui porte la cle privee. La distinction n'est pas cosmetique : une carte ou
# une cle USB se restituent en fin de vie et se perdent, un fichier logiciel se
# copie et ne se rend pas.
CERT_SUPPORT_LABELS = {'carte': 'Carte à puce', 'cle_usb': 'Clé USB',
                       'logiciel': 'Fichier logiciel', 'autre': 'Autre'}
# Ce qu'on a DECIDE du certificat -- et rien de ce que les dates disent deja.
# « Expire » n'en est pas : il se deduit de la date de fin, et en faire un choix
# de liste ouvrirait deux facons de dire la meme chose, qui pourraient se
# contredire.
CERT_VALIDITY_LABELS = {'valide': 'Valide', 'revoque': 'Révoqué', 'suspendu': 'Suspendu'}


class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), default='tls', server_default='tls', nullable=False)
    service_name = db.Column(db.String(128), nullable=False)
    # Le domaine ne vaut que pour un certificat TLS : un certificat electronique
    # n'en a pas. NULLABLE depuis qu'ils cohabitent ; la route l'exige encore
    # pour le TLS, ou il est ce qui identifie la fiche.
    domain = db.Column(db.String(256))
    issuer = db.Column(db.String(128))
    # Equipement de l'inventaire qui porte ce certificat (vue 360°), optionnel.
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    equipment = db.relationship('Equipment', backref=db.backref('certificates', lazy='dynamic'))
    issued_at = db.Column(db.Date)
    # NULLABLE : un certificat en cours de commande, ou dont personne n'a encore
    # releve la date, existe quand meme. Refuser la fiche perdrait ce qu'on en
    # sait ; l'orange dira qu'elle est a completer.
    expiry_date = db.Column(db.Date)
    auto_renew = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    histories = db.relationship('CertificateHistory', backref='certificate', lazy='dynamic', cascade='all, delete-orphan')

    # ── Certificat electronique nominatif (kind='signature') ──
    # L'autorite de certification est prise dans l'annuaire des societes :
    # c'est un fournisseur comme un autre, avec son adresse et ses contacts, et
    # rien ne justifierait un second annuaire pour Certinomis et ChamberSign.
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    supplier = db.relationship('Supplier', backref=db.backref('certificates', lazy='dynamic'))
    # Service utilisateur du titulaire. Renseigne pour les agents, souvent vide
    # pour les elus, qui n'en relevent pas.
    service_id = db.Column(db.Integer, db.ForeignKey('user_service.id'), index=True)
    service = db.relationship('UserService', foreign_keys=[service_id],
                              backref=db.backref('certificates', lazy='dynamic'))
    civility = db.Column(db.String(8))
    holder = db.Column(db.String(128))          # le NOM, seul : c'est lui qui trie
    first_name = db.Column(db.String(128))
    # La qualite au titre de laquelle il signe -- Maire, Adjoint, DGA, Agent.
    # C'est elle qui donne sa portee juridique a la signature, pas le service.
    holder_role = db.Column(db.String(128))
    holder_email = db.Column(db.String(120))
    cert_usage = db.Column(db.String(24))
    support = db.Column(db.String(16))
    # Niveau de garantie tel que l'autorite l'atteste : « RGS** », « eIDAS
    # qualifie ». Texte libre plutot qu'enumere, les appellations changeant au
    # rythme des referentiels et non a celui de l'application.
    level = db.Column(db.String(64))
    # Numero de serie porte par le certificat lui-meme : a citer pour une
    # revocation ou une reclamation.
    serial_number = db.Column(db.String(128))
    # Duree commandee, en annees. Ne se deduit pas des dates : elle dit ce qui a
    # ete COMMANDE, quand les dates disent ce qui a ete DELIVRE.
    duration_years = db.Column(db.Integer)
    amount_ttc = db.Column(db.Float)
    budget_code = db.Column(db.String(32))      # imputation (« 60632 »)
    order_signed_on = db.Column(db.Date)        # bon de commande signe le
    # Code remis par l'autorite, a garder sous la main le jour ou il faut agir
    # vite : il invalide le certificat (perte, vol, depart du titulaire).
    #
    # C'est un SECRET OPERATOIRE -- revoquer le certificat d'un elu bloque ses
    # signatures. Il n'est montre qu'a qui peut deja modifier la fiche ; la
    # garde est posee dans la route, pas seulement dans l'affichage.
    revocation_code = db.Column(db.String(64))
    validity = db.Column(db.String(16), default='valide')

    def kind_label(self):
        return CERT_KIND_LABELS.get(self.kind, self.kind or '')

    def civility_label(self):
        return CIVILITY_LABELS.get(self.civility, '')

    def usage_label(self):
        return CERT_USAGE_LABELS.get(self.cert_usage, '')

    def support_label(self):
        return CERT_SUPPORT_LABELS.get(self.support, '')

    def validity_label(self):
        return CERT_VALIDITY_LABELS.get(self.validity, 'Valide')

    def holder_label(self):
        """« M. Jean ARNAUD », dans l'ordre ou on le lit. Le nom seul quand le
        reste manque -- l'inventaire n'a longtemps porte que des patronymes."""
        bouts = [self.civility_label(), self.first_name, self.holder]
        return ' '.join(b for b in bouts if b)

    def label(self):
        """Le nom de la fiche, dans les listes, les alertes et les bilans.

        Un certificat TLS se nomme par son domaine, un certificat electronique
        par son titulaire : coller « service - domaine » sur le second donnerait
        « Mairie - » dans tous les mails."""
        if self.kind == 'signature':
            qui = self.holder_label()
            return f'{self.service_name} - {qui}' if qui else self.service_name
        return f'{self.service_name} - {self.domain}' if self.domain else self.service_name

    def monitored(self):
        """Ce certificat compte-t-il encore parmi les echeances ?

        Un certificat REVOQUE ne l'est plus : il n'est deja plus utilisable, sa
        date ne veut plus rien dire, et le rappeler chaque matin ne ferait
        qu'user l'attention. Un certificat SUSPENDU le redeviendra, et son
        echeance continue donc de compter.

        SANS DATE, il n'y a rien a surveiller non plus : on ne peut pas alerter
        sur une echeance qu'on ignore. La fiche le dit en orange, ce qui appelle
        a la completer -- c'est l'ecran qui reclame, pas le mail du matin."""
        return self.is_active and self.validity != 'revoque' and self.expiry_date is not None

    def days_left(self):
        """Jours restants, ou None quand la date manque."""
        if self.expiry_date is None:
            return None
        return (self.expiry_date - datetime.now(timezone.utc).date()).days

    def status(self):
        # Sans echeance, la fiche est A COMPLETER : l'orange le dit, la ou le
        # vert affirmerait qu'on a verifie.
        if self.expiry_date is None:
            return 'warning'
        if self.validity == 'revoque':
            # Revoque : hors surveillance. Le badge de validite, lui, le dit en
            # toutes lettres a cote -- c'est la qu'on lit ce qui a ete decide.
            return 'success'
        return _status_from_days(self.days_left(), 'THRESHOLD_EXPIRY')


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
    # Logiciel concerne, quand la tache en vise un : mise a jour annuelle,
    # purge, renouvellement, revue des comptes. Optionnel -- une restauration de
    # sauvegarde ou un PCA ne portent sur aucun logiciel en particulier.
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), index=True)
    software = db.relationship('Software', backref=db.backref('tasks', lazy='dynamic'))
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
    # Email du responsable : destinataire du mail de revue / validation des taches.
    responsible_email = db.Column(db.String(120))
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


EQUIPMENT_KIND_LABELS = {
    'vm': 'VM',
    'physical': 'Serveur physique',
    'nas': 'NAS',
    'storage': 'Baie de stockage',
    'network': 'Équipement réseau',   # switch, pare-feu, routeur, borne WiFi
}

# L'inventaire se lit en deux FAMILLES. Un switch n'est pas un serveur : les
# melanger dans une seule liste obligeait a cinq onglets et a un titre qui
# enumere. Chaque famille a son entree de menu et ses propres onglets.
#
# La baie de stockage reste avec les serveurs : elle vit dans la meme salle, se
# garantit et se maintient pareil, et c'est aupres d'eux qu'on la cherche.
EQUIPMENT_FAMILIES = {
    'serveurs': ('vm', 'physical', 'nas', 'storage'),
    'reseau': ('network',),
}
EQUIPMENT_FAMILY_LABELS = {'serveurs': 'Serveurs', 'reseau': 'Réseau'}


def equipment_family(kind):
    """La famille d'une nature. Une nature inconnue retombe cote serveurs —
    c'est la famille ordinaire, et une fiche ne doit pas devenir invisible."""
    for famille, natures in EQUIPMENT_FAMILIES.items():
        if kind in natures:
            return famille
    return 'serveurs'


# Ce que chaque nature porte comme informations. On nomme les GROUPES plutot que
# de repeter des listes de natures dans les formulaires, les fiches et les
# routes : sans cela, ajouter une nature demanderait de retrouver dix endroits,
# et celui qu'on oublierait ne se verrait qu'a l'usage -- un champ qui manque
# sur une fiche ne se signale pas.
EQUIPMENT_KIND_GROUPS = {
    # Materiel, garantie, contrat de maintenance : tout ce qui s'achete et se
    # remplace. Une VM n'a ni numero de serie ni garantie.
    'materiel': ('physical', 'nas', 'storage', 'network'),
    # Volumetrie et protocoles : un NAS et une baie de disques se decrivent
    # pareil.
    'stockage': ('nas', 'storage'),
    # Adresse sur le reseau. Le serveur PHYSIQUE y figure desormais : il en a
    # une comme les autres, et son absence etait un oubli — la fiche n'avait
    # simplement pas d'endroit ou la montrer.
    'reseau': ('vm', 'physical', 'nas', 'storage', 'network'),
    # Masque et VLAN : ce qui compte quand on configure le port, donc la VM et
    # l'equipement reseau lui-meme.
    'vlan': ('vm', 'network'),
    # Supervision en TEXTE (nom de l'outil) : la VM a ses interrupteurs a elle.
    'supervision': ('physical', 'nas', 'storage', 'network'),
    # Ce qui ne concerne que la machine virtuelle : hote, hyperviseur, vCPU.
    'virtualisation': ('vm',),
    # Qui s'en sert.
    'services': ('vm', 'physical'),
    # Usage principal / donnees stockees.
    'usage': ('nas', 'storage'),
    # Plan de reprise : ce dont la perte arrete un service.
    'pra': ('physical', 'storage'),
    # Emplacement physique : tout ce qui occupe une baie.
    'emplacement': ('physical', 'nas', 'storage', 'network'),
    # Interface d'administration.
    'administration': ('nas', 'storage', 'network'),
    # Nombre de ports.
    'ports': ('network',),
}

# Les memes groupes, prets a poser dans un attribut `data-kinds` du formulaire.
EQUIPMENT_KIND_GROUPS_ATTR = {k: ' '.join(v) for k, v in EQUIPMENT_KIND_GROUPS.items()}
ENVIRONMENT_LABELS = {'prod': 'Production', 'preprod': 'Préproduction',
                      'dev': 'Développement', 'decommissioned': 'Décommissionné'}
CRITICALITY_LABELS = {1: '1 - Faible', 2: '2 - Modérée', 3: '3 - Élevée', 4: '4 - Vitale'}
# La couleur du niveau, dans les mots de Bootstrap : la meme du materiel au
# logiciel -- un « 4 » ne change pas de sens d'un ecran a l'autre.
CRITICALITY_COLORS = {1: 'secondary', 2: 'info', 3: 'warning', 4: 'danger'}


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
    # Ou la machine se trouve PHYSIQUEMENT : salle, baie, etage. Distinct de
    # `host_server`, qui designe l'hyperviseur d'une VM. Le champ manquait pour
    # tout le materiel, pas seulement pour le reseau : devant une panne, savoir
    # dans quelle baie aller est la premiere question.
    location = db.Column(db.String(128))
    # Interface d'administration (https://..., ou une IP). Elle ne se devine pas
    # depuis l'adresse de service : un switch s'administre souvent sur un VLAN
    # dedie.
    management_url = db.Column(db.String(256))
    # Nombre de ports : ce qui caracterise un switch, et ce qu'on regarde avant
    # d'en commander un autre.
    ports = db.Column(db.Integer)
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

    def famille(self):
        return equipment_family(self.kind or 'vm')

    def porte(self, groupe):
        """Cette nature d'equipement porte-t-elle ce groupe d'informations ?
        Les fiches s'en servent pour ne montrer que ce qui a un sens."""
        return (self.kind or 'vm') in EQUIPMENT_KIND_GROUPS.get(groupe, ())

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
                        'provider': 'Prestataire', 'operator': 'Opérateur',
                        'ca': 'Autorité de certification', 'other': 'Autre'}


class Supplier(db.Model):
    """Annuaire des societes : qui appeler en cas d'incident (hotline, n°
    client, portail support), mais aussi qui appeler AVANT et APRES -- le
    commercial pour l'offre et le renouvellement, l'administratif pour la
    facturation, le DPO pour les donnees.

    Ces coordonnees ne se saisissent QU'ICI, et les fiches logiciel les
    remontent en lecture seule : la question « qui j'appelle ? » se pose devant
    le logiciel, mais la reponse vaut pour tous ceux du meme editeur. Les
    recopier fiche par fiche garantirait des numeros divergents.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    kind = db.Column(db.String(32), default='provider')  # cf. SUPPLIER_KIND_LABELS
    contact_name = db.Column(db.String(128))   # interlocuteur habituel
    phone = db.Column(db.String(64))           # standard / commercial
    support_phone = db.Column(db.String(64))   # hotline support
    email = db.Column(db.String(128))
    support_url = db.Column(db.String(256))    # portail de tickets
    support_email = db.Column(db.String(128))  # adresse de l'assistance
    customer_ref = db.Column(db.String(128))   # n° client / identifiant support
    hours = db.Column(db.String(128))          # horaires du support (ex. 8h-18h, J+1...)
    # Les horaires tiennent sur DEUX lignes parce qu'ils decrivent presque
    # toujours deux regimes -- « lundi au vendredi 8h-17h » puis « samedi
    # 8h-12h ». Une seule ligne obligeait a les coudre, chaque fiche inventant
    # sa ponctuation.
    hours2 = db.Column(db.String(128))
    # Coordonnees postales et vitrine.
    address = db.Column(db.String(256))
    postal_code = db.Column(db.String(16))
    city = db.Column(db.String(128))
    website = db.Column(db.String(256))
    # ── Contacts hors incident ──
    # Chacun porte le NOM de la personne puis ses coordonnees, distincts du
    # standard (phone/email) qui reste celui de la societe.
    commercial_contact = db.Column(db.String(128))
    commercial_phone = db.Column(db.String(64))
    commercial_email = db.Column(db.String(128))
    # Un SECOND commercial, frequent chez les editeurs qui separent le
    # renouvellement de l'avant-vente, ou pendant une passation.
    commercial_contact2 = db.Column(db.String(128))
    commercial_phone2 = db.Column(db.String(64))
    commercial_email2 = db.Column(db.String(128))
    admin_contact = db.Column(db.String(128))    # facturation
    admin_phone = db.Column(db.String(64))
    admin_email = db.Column(db.String(128))
    # Le DPO de l'EDITEUR -- celui a qui ecrire pour une violation ou une
    # demande d'exercice de droits sur les donnees qu'il heberge. Distinct du
    # DPO de la collectivite, qui n'a pas sa place dans un annuaire de
    # fournisseurs.
    dpo_contact = db.Column(db.String(128))
    dpo_phone = db.Column(db.String(64))
    dpo_email = db.Column(db.String(128))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def kind_label(self):
        return SUPPLIER_KIND_LABELS.get(self.kind, self.kind or '')

    def has_contacts(self):
        """Un contact hors support est-il renseigne ? Sert a n'afficher la
        carte « Contacts » que quand elle a quelque chose a dire."""
        return any([self.commercial_contact, self.commercial_phone, self.commercial_email,
                    self.commercial_contact2, self.commercial_phone2, self.commercial_email2,
                    self.admin_contact, self.admin_phone, self.admin_email,
                    self.dpo_contact, self.dpo_phone, self.dpo_email])


CONTRACT_KIND_LABELS = {'maintenance': 'Maintenance', 'licence': 'Licence',
                        'subscription': 'Abonnement', 'market': 'Marché public',
                        'other': 'Autre'}

# Ce qu'EST l'acte : un marche public passe apres publicite et mise en
# concurrence, ou un contrat de gre a gre. Distinct de CONTRACT_KIND_LABELS,
# qui dit de QUOI il s'agit (maintenance, licence, abonnement).
CONTRACT_NATURE_LABELS = {'marche': 'Marché public', 'contrat': 'Contrat de gré à gré'}

# Nature d'une PIECE du marche : le mode de licence de ce poste-la.
CONTRACT_ITEM_KIND_LABELS = {'abonnement': 'Abonnement', 'perpetuelle': 'Licence perpétuelle',
                             'libre': 'Libre / gratuit', 'autre': 'Autre'}


# Equipements couverts par un contrat (relation N:N). Premiere table
# d'association du projet ; alimentee au demarrage depuis l'ancien equipment_id.
contract_equipment = db.Table(
    'contract_equipment',
    db.Column('contract_id', db.Integer, db.ForeignKey('contract.id'), primary_key=True),
    db.Column('equipment_id', db.Integer, db.ForeignKey('equipment.id'), primary_key=True),
)


# Logiciels couverts par un marche (relation N:N). Un marche en couvre souvent
# PLUSIEURS -- UGAP, marches « communs » a deux applications : il vit donc pour
# lui-meme, et n'est plus une dependance du logiciel. Le lien ne porte rien de
# son cote ; tout appartient au marche.
contract_software = db.Table(
    'contract_software',
    db.Column('contract_id', db.Integer, db.ForeignKey('contract.id'), primary_key=True),
    db.Column('software_id', db.Integer, db.ForeignKey('software.id'), primary_key=True),
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
    # Marche public ou gre a gre. NULL = non renseigne : les lignes reprises de
    # l'historique n'ont pas ete depouillees sur ce point, et rien ne permet de
    # trancher a leur place -- l'ecran dit « — » plutot qu'une supposition.
    nature = db.Column(db.String(16))
    reference = db.Column(db.String(128))      # n° de contrat / de marche (le NOTRE)
    # La reference que LE FOURNISSEUR donne au meme acte -- son numero de
    # commande ou de contrat pour cette affaire. C'est celle-la qu'il faut citer
    # quand on l'appelle, et personne ne la retrouvait.
    supplier_reference = db.Column(db.String(128))
    cost_yearly = db.Column(db.Float)          # cout annuel TTC : CE QU'ON PAIE
    # Maximum ANNUEL, quand l'acte en fixe un. Ne contraint pas cost_yearly :
    # c'est l'acte qui fait foi, pas l'outil. Un plafond n'est pas une depense,
    # et n'entre donc pas dans le cout du parc.
    cost_max_yearly = db.Column(db.Float)
    # Ce que pese le marche sur sa DUREE ENTIERE, quand l'acte le chiffre.
    # N'entre pas non plus dans le cout du parc, qui se compte a l'annee :
    # l'y ajouter gonflerait le total autant de fois que le marche dure.
    cost_total = db.Column(db.Float)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)              # echeance du contrat
    # Duree FERME en annees, telle que l'acte la fixe. Ne se deduit pas des
    # dates : la periode court du debut a la fin reconductions comprises, la
    # duree ferme est l'engagement initial.
    firm_years = db.Column(db.Integer)
    # « Renouvelable n fois » : zero est une VALEUR (marche sec, non
    # reconductible), distincte de NULL qui dit que l'acte n'a pas ete depouille.
    renewals = db.Column(db.Integer)
    # Duree de CHAQUE reconduction, en annees. Se lit avec `renewals`, qui dit
    # combien de fois quand celui-ci dit pour combien de temps -- une
    # reconduction annuelle et une triennale ne pesent pas le meme engagement.
    renewal_years = db.Column(db.Integer)
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
    # Logiciels couverts (M:N). Remplace l'ancien Software.contract_id, qui ne
    # savait pas dire qu'un marche en couvre plusieurs.
    software = db.relationship('Software', secondary=contract_software,
                               backref=db.backref('contracts', lazy='dynamic'))
    items = db.relationship('ContractItem', backref='contract', lazy='dynamic',
                            cascade='all, delete-orphan',
                            order_by='ContractItem.doc_date.desc()')
    # Imputation budgetaire (« 6156 », « 65818 ») : la ligne du budget sur
    # laquelle la depense tombe. Meme champ que sur un certificat, ou il rend
    # deja le meme service -- la comptabilite pose la question pour les deux.
    budget_code = db.Column(db.String(32))
    # Le bon de commande signe et envoye. L'acte notifie n'engage la prestation
    # qu'une fois ce bon parti ; c'est l'etape qu'on oublie, et la seule dont la
    # date se retient.
    order_signed_on = db.Column(db.Date)
    # Le service pour qui l'acte est passe. Un contrat couvre le plus souvent des
    # logiciels, qui portent deja leurs services -- mais une cotisation, une
    # liaison fibre ou un abonnement n'en couvre aucun, et le service se perdait.
    service_id = db.Column(db.Integer, db.ForeignKey('user_service.id'), index=True)
    service = db.relationship('UserService', foreign_keys=[service_id],
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

    def nature_label(self):
        return CONTRACT_NATURE_LABELS.get(self.nature, '')

    def period_label(self):
        """« du 01/01/2023 au 31/12/2026 », et ce que l'on sait quand il manque
        une des deux dates : un marche en cours a souvent un debut connu et un
        terme qui ne l'est pas."""
        d = self.start_date.strftime('%d/%m/%Y') if self.start_date else None
        f = self.end_date.strftime('%d/%m/%Y') if self.end_date else None
        if d and f:
            return f'du {d} au {f}'
        if d:
            return f'depuis le {d}'
        if f:
            return f"jusqu'au {f}"
        return ''

    def renewal_label(self):
        """« renouvelable 2 fois par periode de 1 an ». Zero se dit aussi :
        « non reconductible » est une information, pas un vide."""
        if self.renewals is None:
            return ''
        if self.renewals == 0:
            return 'non reconductible'
        fois = 'fois' if self.renewals > 1 else 'fois'
        if self.renewal_years:
            an = 'an' if self.renewal_years == 1 else 'ans'
            return f'renouvelable {self.renewals} {fois} par période de {self.renewal_years} {an}'
        return f'renouvelable {self.renewals} {fois}'

    def items_cost(self):
        """Somme des couts des pieces. INDICATIVE : c'est `cost_yearly` qui
        engage. Un marche couvre souvent plusieurs postes dont la somme ne vaut
        pas le montant de l'acte."""
        return sum(i.cost_yearly or 0 for i in self.items)

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


class ContractItem(db.Model):
    """Une PIECE du marche : un poste, son cout annuel, et la date de son
    document (signature, notification).

    Elle ne decrit qu'elle-meme. Elle ne porte PAS d'echeance : c'est le marche
    qui engage, et c'est sa date de fin qu'on surveille. Un meme marche couvre
    souvent plusieurs postes aux couts et aux termes distincts, sans que leur
    somme ni leur echeance la plus lointaine vaillent engagement -- d'ou la
    separation.
    """
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False, index=True)
    label = db.Column(db.String(128))     # ex. « 50 postes », « module RH »
    kind = db.Column(db.String(16), default='abonnement')
    cost_yearly = db.Column(db.Float)
    # La date du DOCUMENT, presque toujours passee : aucun rappel n'y est
    # accroche.
    doc_date = db.Column(db.Date, index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def kind_label(self):
        return CONTRACT_ITEM_KIND_LABELS.get(self.kind, self.kind or '')


class Consultation(db.Model):
    """Une mise en concurrence sur un logiciel : l'objet consulte
    (renouvellement, migration, premiere acquisition...) et les devis recus.

    Un niveau INTERMEDIAIRE, et non une liste plate de devis : un logiciel en
    accumule plusieurs au fil des annees, et une liste plate ne saurait pas dire
    quel devis a ete retenu pour quelle consultation.
    """
    id = db.Column(db.Integer, primary_key=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=False, index=True)
    software = db.relationship('Software', backref=db.backref(
        'consultations', lazy='dynamic', cascade='all, delete-orphan'))
    subject = db.Column(db.String(256), nullable=False)
    date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    quotes = db.relationship('Quote', backref='consultation', lazy='dynamic',
                             cascade='all, delete-orphan')

    def selected_quote(self):
        """Le devis retenu, s'il y en a un. AU PLUS UN par consultation :
        l'invariant est tenu par la route qui marque (voir contracts.py)."""
        return self.quotes.filter_by(selected=True).first()


class Quote(db.Model):
    """Devis recu dans le cadre d'une consultation."""
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation.id'),
                                nullable=False, index=True)
    # Societe qui a remis le devis. NULL quand elle n'est pas dans l'annuaire :
    # l'historique de la consultation vaut d'etre garde meme sans fiche.
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    supplier = db.relationship('Supplier', backref=db.backref('quotes', lazy='dynamic'))
    supplier_name = db.Column(db.String(128))  # repli quand la societe n'a pas de fiche
    amount = db.Column(db.Float)
    date = db.Column(db.Date)
    selected = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def who(self):
        return self.supplier.name if self.supplier else (self.supplier_name or '—')


class Referential(db.Model):
    """Liste de valeurs administrable : technologies applicatives, categories de
    pieces jointes, types de taches recurrentes...

    UNE table pour toutes ces listes, distinguees par `kind`, plutot qu'une
    table par liste : elles ont toutes exactement la meme forme -- un libelle et
    un rang d'affichage -- et n'appellent chacune ni ecran ni logique propre.
    En ouvrir une nouvelle ne coute alors qu'une cle dans REFERENTIAL_KINDS.

    Les valeurs de la logique metier (statut, criticite, hebergement) ne sont
    PAS ici : elles pilotent des calculs et des filtres, et pouvoir en ajouter
    ou en retirer laisserait des fiches orphelines. Elles restent des constantes.
    """
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(32), nullable=False, index=True)
    label = db.Column(db.String(64), nullable=False)
    position = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    __table_args__ = (db.UniqueConstraint('kind', 'label', name='uq_referential_kind_label'),)

    @staticmethod
    def options(kind):
        """Les valeurs actives d'une liste, dans l'ordre d'affichage."""
        return (Referential.query
                .filter_by(kind=kind, is_active=True)
                .order_by(Referential.position, Referential.label).all())


REFERENTIAL_KINDS = {
    'technology': 'Technologies applicatives',
    'doc_category': 'Catégories de pièces jointes',
    'task_type': 'Types de tâches récurrentes',
}

# Valeurs de depart, versees au premier demarrage (cf. _seed_referentials).
REFERENTIAL_SEEDS = {
    'technology': ['Web', 'Client lourd', 'Client-serveur', 'Mobile', 'Service système'],
    'doc_category': ['Contrat / marché', 'Devis', 'Guide utilisateur',
                     'Documentation technique', 'Délibération', 'Arrêté', 'Autre'],
    'task_type': ['Mise à jour', 'Renouvellement de contrat', 'Purge',
                  'Revue des comptes', 'Renouvellement de certificat'],
}

# Services utilisateurs d'un logiciel (relation N:N). Un logiciel sert souvent
# plusieurs directions -- l'etat civil ET l'urbanisme pour un parapheur --, et
# une direction en utilise plusieurs.
software_service = db.Table(
    'software_service',
    db.Column('software_id', db.Integer, db.ForeignKey('software.id'), primary_key=True),
    db.Column('user_service_id', db.Integer, db.ForeignKey('user_service.id'), primary_key=True),
)


class UserService(db.Model):
    """Service utilisateur : la direction ou le service de la collectivite qui
    se sert d'un logiciel -- etat civil, urbanisme, finances, RH.

    Une TABLE et non une simple liste de libelles (cf. `Referential`) : un
    service a un referent, avec son adresse et son telephone. C'est a lui qu'on
    ecrit pour une revue de droits ou une coupure, et le chercher ailleurs a
    chaque fois est precisement ce qu'un inventaire doit eviter.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    contact_name = db.Column(db.String(128))
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(64))
    position = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def options():
        return (UserService.query.filter_by(is_active=True)
                .order_by(UserService.position, UserService.name).all())


class SoftwareLink(db.Model):
    """Flux ORIENTE entre deux logiciels : « export paie mensuel vers X ».

    Le sens compte -- savoir que la paie alimente la comptabilite, et non
    l'inverse, est tout l'interet de la ligne. La fiche d'un logiciel montre
    donc les DEUX sens, en les distinguant.
    """
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=False, index=True)
    target_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=False, index=True)
    description = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    source = db.relationship('Software', foreign_keys=[source_id],
                             backref=db.backref('links_out', lazy='dynamic',
                                                cascade='all, delete-orphan'))
    target = db.relationship('Software', foreign_keys=[target_id],
                             backref=db.backref('links_in', lazy='dynamic',
                                                cascade='all, delete-orphan'))
    # Le meme flux deux fois n'apprend rien a personne.
    __table_args__ = (db.UniqueConstraint('source_id', 'target_id', name='uq_link_source_target'),)


class SoftwareShare(db.Model):
    """Un dossier du PARTAGE RESEAU rattache a un logiciel : la ou vivent ses
    installeurs, ses outils, ses notes de version -- tout ce qui est trop lourd
    ou trop vivant pour une piece jointe, qui ne recoit que des actes figes.

    Une TABLE et non un champ sur le logiciel : les dossiers d'une application
    se comptent rarement a l'unite -- les installeurs d'un cote, la
    documentation de l'editeur de l'autre --, et rien ne dirait lequel est
    « le » bon.

    Le chemin est un chemin WINDOWS, pas une URL : l'application l'AFFICHE et le
    fait COPIER, elle ne l'ouvre jamais. Un navigateur refuse de suivre un lien
    `file://` pose par une page servie en http(s) -- le clic ne ferait rien,
    sans meme un message. C'est a l'Explorateur de l'ouvrir, et les droits du
    partage decident seuls de qui y entre.
    """
    id = db.Column(db.Integer, primary_key=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=False, index=True)
    # A quoi sert ce dossier. FACULTATIF : un chemin qui finit par le nom du
    # logiciel se passe de legende.
    label = db.Column(db.String(128))
    path = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    software = db.relationship('Software', backref=db.backref(
        'shares', lazy='dynamic', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('software_id', 'path', name='uq_share_software_path'),)


# ── Qualification d'un logiciel ──
# Ces listes pilotent des filtres, des compteurs et des couleurs : elles restent
# des CONSTANTES, la ou les libelles purement descriptifs vivent en base
# (Referential). Une valeur qu'on peut ajouter est une valeur dont aucun calcul
# ne depend.
HOSTING_LABELS = {'on_premise': 'On premise', 'saas': 'SaaS (hors parc)',
                  'hybride': 'Hybride'}
LIFECYCLE_LABELS = {'evaluation': 'En évaluation', 'production': 'En production',
                    'fin_de_vie': 'En fin de vie', 'abandonne': 'Abandonné'}
# Couleur du badge de cycle de vie, dans les mots de Bootstrap.
LIFECYCLE_COLORS = {'evaluation': 'info', 'production': 'success',
                    'fin_de_vie': 'warning', 'abandonne': 'secondary'}
SOURCE_TYPE_LABELS = {'proprietaire': 'Propriétaire', 'opensource': 'Open source',
                      'mixte': 'Mixte'}
AUTH_MODE_LABELS = {'locale': 'Comptes locaux', 'ldap': 'Annuaire (LDAP/AD)',
                    'sso': "SSO / fournisseur d'identité",
                    'mixte_ldap': 'Locale + annuaire', 'mixte_sso': 'Locale + SSO',
                    'aucune': 'Aucune'}
DATA_LOCATION_LABELS = {'ue': 'Union européenne', 'hors_ue': 'Hors UE',
                        'mixte': 'Mixte', 'inconnue': 'Non renseignée'}


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
    version = db.Column(db.String(64))
    # Hebergement : « on premise » / « SaaS » / « hybride ». L'ancien booleen
    # is_saas ne savait pas dire « hybride » -- une part chez nous, une part
    # dehors --, cas qui se rencontre des qu'un logiciel installe expose un
    # portail heberge par l'editeur. Il survit en PROPRIETE calculee : tout ce
    # qui n'est pas entierement chez nous echappe au parc, et c'est ce que le
    # booleen voulait dire.
    hosting = db.Column(db.String(16), default='on_premise', server_default='on_premise',
                        nullable=False)
    is_docker = db.Column(db.Boolean, default=False)  # conteneurise (Docker), cumulable avec SaaS ou on premise
    # Fait et maintenu par la DSI : ni editeur, ni support, ni contrat a
    # rattacher. Porte par le logiciel plutot que par un fournisseur fictif
    # « Developpement interne », qui polluerait l'annuaire.
    internal_dev = db.Column(db.Boolean, default=False)
    # Ne s'installe sur AUCUNE machine du parc (SaaS, ou postes des agents).
    # Sans ce marqueur, une fiche sans serveur ne se distingue pas d'une fiche
    # dont le serveur reste a saisir.
    no_server = db.Column(db.Boolean, default=False)
    lifecycle = db.Column(db.String(16), default='production', server_default='production',
                          nullable=False)
    source_type = db.Column(db.String(16), default='proprietaire')
    # Technologie applicative (Referential kind='technology').
    technology_id = db.Column(db.Integer, db.ForeignKey('referential.id'), index=True)
    technology = db.relationship('Referential', foreign_keys=[technology_id])
    # Mode d'authentification. NULL = non renseigne : un defaut « locale » se
    # serait ecrit sur toute fiche creee et aurait fait dire a l'inventaire ce
    # que personne n'a saisi.
    auth_mode = db.Column(db.String(16))
    auth_strong = db.Column(db.Boolean, default=False)  # 2FA / MFA exigee
    # Utilisateurs reels ; NULL = non compte. Un logiciel a zero utilisateur est
    # un candidat au retrait, un logiciel non compte n'est qu'un trou.
    users_count = db.Column(db.Integer)
    users_max = db.Column(db.Integer)   # plafond contractuel ; NULL = illimite
    service_date = db.Column(db.Date)   # mise en service
    tech_responsible = db.Column(db.String(128))
    tech_responsible_email = db.Column(db.String(120))
    # Remplace le « Aucun contrat » de la fiche quand le marche est porte
    # ailleurs (« gere par le CCAS ») : sans ce mot, le vide se lit comme un
    # trou dans l'inventaire.
    no_contract_note = db.Column(db.String(256))
    # ── Volet RGPD ──
    gdpr_personal_data = db.Column(db.Boolean, default=False)
    gdpr_categories = db.Column(db.String(256))   # etat civil, sante, NIR...
    gdpr_registry_ref = db.Column(db.String(64))  # reference au registre des traitements
    gdpr_location = db.Column(db.String(16), default='inconnue')
    url = db.Column(db.String(256))
    criticality = db.Column(db.Integer)             # 1-4
    responsible = db.Column(db.String(128))
    # Email du responsable de l'application : permet de le notifier directement
    # (coupure d'acces, revue de droits...), y compris via l'API Sesame.
    responsible_email = db.Column(db.String(120))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    # Services utilisateurs (M:N) : les directions qui s'en servent.
    user_services = db.relationship('UserService', secondary=software_service,
                                    backref=db.backref('software', lazy='dynamic'))
    # Serveur(s) d'installation (M:N). Backref Equipment.software_list.
    equipments = db.relationship('Equipment', secondary=software_equipment,
                                 backref=db.backref('software_list', lazy='dynamic'))
    # Mises a jour rattachees (via SystemUpdate.software_id) : backref .software.
    system_updates = db.relationship('SystemUpdate', backref='software', lazy='dynamic')

    @property
    def is_saas(self):
        """Heberge hors parc. `hybride` compte comme SaaS : des qu'une part est
        hebergee dehors, elle echappe au parc -- c'est ce que le booleen dit."""
        return self.hosting in ('saas', 'hybride')

    def hosting_label(self):
        return HOSTING_LABELS.get(self.hosting, self.hosting or '')

    def lifecycle_label(self):
        return LIFECYCLE_LABELS.get(self.lifecycle, self.lifecycle or '')

    def lifecycle_color(self):
        return LIFECYCLE_COLORS.get(self.lifecycle, 'secondary')

    def source_type_label(self):
        return SOURCE_TYPE_LABELS.get(self.source_type, self.source_type or '')

    def auth_mode_label(self):
        return AUTH_MODE_LABELS.get(self.auth_mode, self.auth_mode or '')

    def gdpr_location_label(self):
        return DATA_LOCATION_LABELS.get(self.gdpr_location, self.gdpr_location or '')

    def criticality_label(self):
        """« 3 - Elevee » plutot que « 3 » : le chiffre seul ne dit pas dans
        quel sens il se lit, et la fiche est le seul ecran ou on le rencontre
        hors d'une colonne qui le legende."""
        return CRITICALITY_LABELS.get(self.criticality, '')

    def criticality_color(self):
        return CRITICALITY_COLORS.get(self.criticality, 'secondary')

    def over_licence(self):
        """Le plafond contractuel d'utilisateurs est-il depasse ? None quand
        l'un des deux nombres manque : sans les deux, il n'y a rien a comparer,
        et repondre « non » laisserait croire qu'on a verifie."""
        if self.users_count is None or self.users_max is None:
            return None
        return self.users_count > self.users_max

    def computed_status(self):
        """Statut agrege sur les MAJ liees : rouge si critique, orange si une
        MAJ est disponible, vert sinon.

        Le cycle de vie s'y ajoute : un logiciel « en fin de vie » est une
        echeance, au meme titre qu'une mise a jour en attente -- il faut lui
        trouver un successeur. Un logiciel « abandonne » ne se surveille plus
        (il n'est plus en service) et reste vert."""
        updates = self.system_updates.filter_by(is_active=True).all()
        if any(u.status == 'critical' for u in updates):
            return 'danger'
        if any(u.status == 'update_available' for u in updates):
            return 'warning'
        if self.lifecycle == 'fin_de_vie':
            return 'warning'
        return 'success'


# Les parents possibles d'une piece jointe : la colonne qui la rattache, et la
# categorie de droits qui decide qui peut la deposer et la retirer. Une piece
# suit la fiche a laquelle elle est accrochee -- lire un marche et lire ses
# pieces sont la meme permission.
DOCUMENT_PARENTS = {
    'software': ('software_id', 'inventory'),
    'supplier': ('supplier_id', 'contracts'),
    'contract': ('contract_id', 'contracts'),
    'contract_item': ('contract_item_id', 'contracts'),
    'quote': ('quote_id', 'contracts'),
    'certificate': ('certificate_id', 'certificates'),
    'equipment': ('equipment_id', 'inventory'),
}


class Document(db.Model):
    """Piece jointe : un fichier accroche a une fiche.

    Les OCTETS vivent a part, dans `DocumentContent`. Lister les pieces d'une
    fiche lit alors des metadonnees de quelques octets et jamais les megaoctets
    du fichier : une jointure oubliee ne peut pas couter cher par accident.

    Ils vivent en BASE et non sur le disque : une sauvegarde de la base est
    complete a elle seule, aucun fichier ne peut se retrouver orphelin d'une
    ligne ni une ligne d'un fichier, et le chemin d'acces ne vient jamais du
    client -- le telechargement se fait par identifiant, et rien d'autre.
    """
    id = db.Column(db.Integer, primary_key=True)
    # EXACTEMENT UN parent est renseigne. Une contrainte SQL le dirait mieux,
    # mais SQLite ne sait pas l'ajouter a une table existante : la garde est
    # dans la route qui depose, seule porte d'entree.
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), index=True)
    contract_item_id = db.Column(db.Integer, db.ForeignKey('contract_item.id'), index=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), index=True)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificate.id'), index=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), index=True)
    # Categorie de piece (Referential kind='doc_category') : contrat, guide,
    # deliberation, arrete...
    category_id = db.Column(db.Integer, db.ForeignKey('referential.id'), index=True)
    category = db.relationship('Referential', foreign_keys=[category_id])

    filename = db.Column(db.String(256), nullable=False)   # nom d'origine
    mime = db.Column(db.String(128))
    size = db.Column(db.Integer)
    # Deposant DENORMALISE : la trace survit a la suppression du compte.
    uploaded_by = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    content = db.relationship('DocumentContent', backref='document', uselist=False,
                              cascade='all, delete-orphan')

    def parent_kind(self):
        """Le type de parent auquel cette piece est accrochee."""
        for kind, (col, _cat) in DOCUMENT_PARENTS.items():
            if getattr(self, col, None):
                return kind
        return None

    def permission_category(self):
        """La categorie de droits a exiger pour la lire ou la retirer. Sans
        parent identifiable, on retombe sur la plus restrictive plutot que sur
        la plus permissive : une piece orpheline ne s'ouvre pas au premier
        venu."""
        kind = self.parent_kind()
        return DOCUMENT_PARENTS[kind][1] if kind else 'contracts'

    def size_label(self):
        """La taille dans l'unite ou on la lit : « 1,2 Mo » et non 1258291."""
        n = self.size or 0
        if n < 1024:
            return f'{n} o'
        if n < 1024 * 1024:
            return f'{n / 1024:.0f} Ko'
        return f'{n / (1024 * 1024):.1f} Mo'.replace('.', ',')


class DocumentContent(db.Model):
    """Les octets d'une piece jointe, dans une table A PART (cf. Document).
    Le contenu suit la ligne a la suppression (cascade cote relation)."""
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), primary_key=True)
    data = db.Column(db.LargeBinary, nullable=False)


class SchedulerRun(db.Model):
    """Trace d'execution d'un job planifie (diagnostic des alertes)."""
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(64))
    status = db.Column(db.String(20))  # ok / error
    message = db.Column(db.Text)
    run_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ImportMap(db.Model):
    """Correspondance entre l'identifiant d'un objet dans l'outil D'ORIGINE et
    celui de la fiche creee ici par la reprise.

    C'est ce qui rend la reprise REJOUABLE : relancer le script sur une base a
    moitie versee retrouve les fiches deja creees au lieu de les doubler. La
    premiere passe revele toujours quelque chose a corriger, et sans cette
    table il faudrait vider la base entre deux essais.

    UNE table pour tous les types plutot qu'une colonne par modele : la
    correspondance ne concerne qu'un import, pas la vie des fiches, et elle
    s'efface d'un DELETE le jour ou la reprise est derriere nous.
    """
    kind = db.Column(db.String(32), primary_key=True)
    remote_id = db.Column(db.Integer, primary_key=True)
    local_id = db.Column(db.Integer, nullable=False)


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
