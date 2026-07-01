from datetime import datetime, timezone
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=['200 per minute', '2000 per hour'])


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    _weak_secrets = {'dev-secret-key', 'dev-secret-key-change-in-production'}
    if not app.config.get('APP_DEBUG') and app.config.get('SECRET_KEY') in _weak_secrets:
        raise RuntimeError(
            "SECRET_KEY non configure. Definissez une valeur forte dans .env "
            "(ex: python -c \"import secrets; print(secrets.token_hex(32))\") "
            "avant de demarrer hors mode debug."
        )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    _setup_logging(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'

    @app.context_processor
    def inject_now():
        from app.snooze import get_active_snooze

        def role_label(name):
            labels = {'admin': 'Administrateur', 'editor': 'Éditeur', 'viewer': 'Lecteur'}
            return labels.get(name, (name or '').replace('-', ' ').replace('_', ' ').title())

        return {'now': lambda: datetime.now(timezone.utc),
                'active_snooze': get_active_snooze,
                'role_label': role_label}

    # Compteurs de la sidebar : leur calcul charge toutes les tables et evalue
    # chaque statut. On le fait au plus une fois par minute (cache process,
    # waitress mono-process), pas a chaque requete. Les badges peuvent donc
    # avoir jusqu'a 60 s de retard, sans impact metier.
    _nav_cache = {'at': 0.0, 'danger': None, 'trash': None}
    _NAV_TTL = 60

    @app.context_processor
    def inject_nav_counts():
        import time
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {}
        from app.models import (Account, Certificate, Domain, Backup, TestTask,
                                AccessReview, SystemUpdate, Equipment, Role,
                                Contract)

        trash_models = [('accounts', Account), ('certificates', Certificate),
                        ('domains', Domain), ('backups', Backup), ('tests', TestTask),
                        ('reviews', AccessReview), ('updates', SystemUpdate),
                        ('inventory', Equipment), ('contracts', Contract)]

        if _nav_cache['danger'] is None or time.monotonic() - _nav_cache['at'] > _NAV_TTL:
            # Les elements snoozes sont exclus des badges, comme du digest :
            # un report d'alerte acquitte ne doit plus compter en « danger ».
            from app.models import AlertSnooze
            today = datetime.now(timezone.utc).date()
            snoozed = {}
            for s in AlertSnooze.query.filter(AlertSnooze.snoozed_until >= today).all():
                snoozed.setdefault(s.entity_type, set()).add(s.entity_id)

            def _danger(items, method, etype):
                skip = snoozed.get(etype, ())
                return sum(1 for i in items
                           if i.id not in skip and getattr(i, method)() == 'danger')

            _nav_cache['danger'] = {
                'accounts': _danger(Account.query.filter_by(is_active=True).all(), 'status', 'account'),
                'certificates': _danger(Certificate.query.filter_by(is_active=True).all(), 'status', 'certificate'),
                'domains': _danger(Domain.query.filter_by(is_active=True).all(), 'status', 'domain'),
                'backups': _danger(Backup.query.filter_by(is_active=True).all(), 'computed_status', 'backup'),
                'tests': _danger(TestTask.query.filter_by(is_active=True).all(), 'computed_status', 'test'),
                'reviews': _danger(AccessReview.query.filter_by(is_active=True).all(), 'computed_status', 'review'),
                'updates': _danger(SystemUpdate.query.filter_by(is_active=True).all(), 'status_color', 'update'),
                'inventory': _danger(Equipment.query.filter_by(is_active=True).all(), 'computed_status', 'equipment'),
                'contracts': _danger(Contract.query.filter_by(is_active=True).all(), 'status', 'contract'),
            }
            # Corbeille : compte par categorie (la somme visible depend des
            # droits de chaque utilisateur, appliquee plus bas hors cache).
            _nav_cache['trash'] = {cat: m.query.filter_by(is_active=False).count()
                                   for cat, m in trash_models}
            _nav_cache['at'] = time.monotonic()

        counts = dict(_nav_cache['danger'])
        counts['trash'] = sum(n for cat, n in _nav_cache['trash'].items()
                              if current_user.can_edit(cat))
        return {'nav_counts': counts, 'all_roles': Role.query.order_by(Role.name).all()}

    @app.after_request
    def _security_headers(resp):
        # Durcissement HTTP. Tous les assets sont servis en local (static/vendor),
        # mais les templates utilisent des scripts/styles inline -> 'unsafe-inline'.
        # img-src data: pour le QR code 2FA.
        h = resp.headers
        h.setdefault('X-Content-Type-Options', 'nosniff')
        h.setdefault('X-Frame-Options', 'DENY')
        h.setdefault('Referrer-Policy', 'same-origin')
        h.setdefault('Content-Security-Policy',
                     "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                     "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                     "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                     "base-uri 'self'; form-action 'self'")
        return resp

    @app.before_request
    def _enforce_admin_2fa():
        # 2FA obligatoire pour les admins (si active) : tant qu'un admin n'a pas
        # de TOTP, on ne l'autorise que sur son profil (pour l'activer), la
        # deconnexion, la verif 2FA et les assets.
        if not app.config.get('REQUIRE_2FA_ADMIN'):
            return
        from flask import request, redirect, url_for, flash
        from flask_login import current_user
        if not current_user.is_authenticated or current_user.has_2fa or not current_user.is_admin:
            return
        allowed = {'auth.profile', 'auth.logout', 'auth.two_factor', 'auth.login', 'static'}
        if request.endpoint in allowed:
            return
        flash("Sécurité : activez la double authentification pour continuer "
              "(obligatoire pour les comptes administrateur).", 'warning')
        return redirect(url_for('auth.profile'))

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.accounts import bp as accounts_bp
    app.register_blueprint(accounts_bp, url_prefix='/accounts')

    from app.certificates import bp as certificates_bp
    app.register_blueprint(certificates_bp, url_prefix='/certificates')

    from app.domains import bp as domains_bp
    app.register_blueprint(domains_bp, url_prefix='/domains')

    from app.backups import bp as backups_bp
    app.register_blueprint(backups_bp, url_prefix='/backups')

    from app.tests import bp as tests_bp
    app.register_blueprint(tests_bp, url_prefix='/tests')

    from app.reviews import bp as reviews_bp
    app.register_blueprint(reviews_bp, url_prefix='/reviews')

    from app.updates import bp as updates_bp
    app.register_blueprint(updates_bp, url_prefix='/updates')

    from app.inventory import bp as inventory_bp
    app.register_blueprint(inventory_bp, url_prefix='/inventory')

    from app.contracts import bp as contracts_bp
    app.register_blueprint(contracts_bp, url_prefix='/contracts')

    from app.suppliers import bp as suppliers_bp
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')

    from app.alerts import bp as alerts_bp
    app.register_blueprint(alerts_bp, url_prefix='/alerts')

    from app.users import bp as users_bp
    app.register_blueprint(users_bp, url_prefix='/users')

    from app.search import bp as search_bp
    app.register_blueprint(search_bp)

    from app.data_io import bp as data_io_bp
    app.register_blueprint(data_io_bp, url_prefix='/data')
    from app.health import bp as health_bp
    app.register_blueprint(health_bp)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp)

    from app.pdf_export import bp as pdf_export_bp
    app.register_blueprint(pdf_export_bp)

    with app.app_context():
        _setup_sqlite()
        _drop_legacy_login_throttle()
        db.create_all()
        _auto_migrate_sqlite()
        _migrate_data()
        _seed_roles()
        _seed_default_user()
        # Configuration applicative persistee en base (messagerie, LDAP, seuils,
        # webhooks...). seed_from_env migre l'existant .env au 1er demarrage,
        # puis load() applique la base (source de verite) sur app.config.
        from app import config_store
        config_store.seed_from_env(app)
        config_store.load(app)

    from app.scheduler import start_scheduler
    if not app.config.get('TESTING'):
        start_scheduler(app)

    return app


def _setup_logging(app):
    """Journalisation applicative JSON dans un fichier avec rotation.
    Format JSON pour faciliter l'ingestion par des agrégateurs de logs."""
    if app.config.get('TESTING'):
        return
    import os
    import logging
    import json as _json
    from logging.handlers import RotatingFileHandler

    class _JsonFormatter(logging.Formatter):
        def format(self, record):
            doc = {
                'ts': self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
                'level': record.levelname,
                'logger': record.name,
                'msg': record.getMessage(),
            }
            if record.exc_info:
                doc['exc'] = self.formatException(record.exc_info)
            return _json.dumps(doc, ensure_ascii=False)

    log_dir = os.path.join(app.instance_path, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(os.path.join(log_dir, 'sentinelle.log'),
                                  maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Sentinelle demarre')


def _migrate_data():
    """Petites migrations de donnees idempotentes (valeurs renommees)."""
    from sqlalchemy import text
    # Le type d'asset « server » est remplace par « divers » (les serveurs sont
    # desormais geres dans l'inventaire).
    db.session.execute(text("UPDATE asset SET asset_type='divers' WHERE asset_type='server'"))
    db.session.commit()


def _setup_sqlite():
    """Pragmas SQLite pour le multi-thread (waitress) : WAL permet aux lectures
    et ecritures de cohabiter, busy_timeout evite les 'database is locked'
    quand deux ecritures se croisent."""
    from sqlalchemy import event
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return

    @event.listens_for(db.engine, 'connect')
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=5000')
        cur.execute('PRAGMA synchronous=NORMAL')
        cur.close()


def _drop_legacy_login_throttle():
    """L'anti-bruteforce passe d'une cle 'username' (unique) a un couple
    (username, ip). L'ancienne table porte un index unique sur username
    qu'on ne peut pas retirer proprement en SQLite : on la supprime pour la
    laisser recreer au bon schema. Les compteurs d'echec sont ephemeres, leur
    remise a zero est sans consequence."""
    from sqlalchemy import inspect, text
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return
    insp = inspect(db.engine)
    if 'login_throttle' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('login_throttle')}
    if 'ip' not in cols:  # schema legacy
        db.session.execute(text('DROP TABLE login_throttle'))
        db.session.commit()


def _auto_migrate_sqlite():
    """Ajoute les colonnes et index manquants aux tables SQLite existantes
    (create_all ne modifie pas une table deja creee). Pratique a chaque ajout
    de champ ou d'index."""
    from sqlalchemy import inspect, text
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    for table in db.metadata.sorted_tables:
        if table.name not in existing:
            continue  # nouvelle table : create_all s'en charge
        cols = {c['name'] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in cols:
                coltype = col.type.compile(db.engine.dialect)
                db.session.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
        # Index declares dans les modeles (index=True / db.Index) : create_all
        # ne les ajoute pas non plus sur une table existante.
        for idx in table.indexes:
            idx_cols = ', '.join(f'"{c.name}"' for c in idx.columns)
            unique = 'UNIQUE ' if idx.unique else ''
            db.session.execute(text(
                f'CREATE {unique}INDEX IF NOT EXISTS "{idx.name}" ON "{table.name}" ({idx_cols})'))
    db.session.commit()


def _seed_roles():
    from app.models import Role, PERMISSION_CATEGORIES

    def editor_level(c):
        return 1 if c == 'alerts' else 3

    def viewer_level(c):
        return 1

    defaults = {
        'admin': {'description': 'Acces total', 'is_admin': True, 'level': None},
        'editor': {'description': 'Gestion des donnees', 'is_admin': False, 'level': editor_level},
        'viewer': {'description': 'Lecture seule', 'is_admin': False, 'level': viewer_level},
    }
    changed = False
    for name, cfg in defaults.items():
        role = Role.query.filter_by(name=name).first()
        if role is None:
            perms = {} if cfg['level'] is None else {c: cfg['level'](c) for c in PERMISSION_CATEGORIES}
            db.session.add(Role(name=name, description=cfg['description'],
                                is_admin=cfg['is_admin'], permissions=perms))
            changed = True
        elif not role.is_admin and cfg['level']:
            # complete les categories manquantes (ex. ajout d'un nouveau module)
            # sans ecraser les niveaux deja personnalises.
            perms = dict(role.permissions or {})
            missing = False
            for c in PERMISSION_CATEGORIES:
                if c not in perms:
                    perms[c] = cfg['level'](c)
                    missing = True
            if missing:
                role.permissions = perms
                changed = True
    if changed:
        db.session.commit()


def _seed_default_user():
    import os
    import secrets
    from app.models import User

    def _new_password():
        return os.getenv('ADMIN_INITIAL_PASSWORD') or secrets.token_urlsafe(12)

    def _announce(password, created):
        action = 'cree' if created else 'reinitialise (mot de passe par defaut detecte)'
        print('\n' + '=' * 64)
        print(f"  COMPTE ADMIN {action}")
        print("  Identifiant : admin")
        print(f"  Mot de passe: {password}")
        print("  -> Connectez-vous puis changez-le via votre profil.")
        print('=' * 64 + '\n')

    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(
            username='admin',
            email=Config.ADMIN_EMAIL or 'admin@localhost',
            role='admin'
        )
        password = _new_password()
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        _announce(password, created=True)
    elif admin.check_password('admin'):
        # Ancien compte avec le mot de passe par defaut: on le regenere.
        password = _new_password()
        admin.set_password(password)
        db.session.commit()
        _announce(password, created=False)
