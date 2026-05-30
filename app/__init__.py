from datetime import datetime, timezone
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf import CSRFProtect
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()


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
    mail.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'

    @app.context_processor
    def inject_now():
        from app.snooze import get_active_snooze
        return {'now': lambda: datetime.now(timezone.utc),
                'active_snooze': get_active_snooze}

    @app.context_processor
    def inject_nav_counts():
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {}
        from app.models import Account, Certificate, Domain, Backup, TestTask, Role

        def _danger(items, method):
            return sum(1 for i in items if getattr(i, method)() == 'danger')

        counts = {
            'accounts': _danger(Account.query.filter_by(is_active=True).all(), 'status'),
            'certificates': _danger(Certificate.query.filter_by(is_active=True).all(), 'status'),
            'domains': _danger(Domain.query.filter_by(is_active=True).all(), 'status'),
            'backups': _danger(Backup.query.filter_by(is_active=True).all(), 'computed_status'),
            'tests': _danger(TestTask.query.filter_by(is_active=True).all(), 'computed_status'),
        }
        return {'nav_counts': counts, 'all_roles': Role.query.order_by(Role.name).all()}

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

    from app.alerts import bp as alerts_bp
    app.register_blueprint(alerts_bp, url_prefix='/alerts')

    from app.users import bp as users_bp
    app.register_blueprint(users_bp, url_prefix='/users')

    from app.search import bp as search_bp
    app.register_blueprint(search_bp)

    from app.data_io import bp as data_io_bp
    app.register_blueprint(data_io_bp, url_prefix='/data')

    with app.app_context():
        db.create_all()
        _seed_roles()
        _seed_default_user()

    from app.scheduler import start_scheduler
    if not app.config.get('TESTING'):
        start_scheduler(app)

    return app


def _seed_roles():
    from app.models import Role, PERMISSION_CATEGORIES
    defaults = {
        'admin': {'description': 'Acces total', 'is_admin': True, 'permissions': {}},
        'editor': {'description': 'Gestion des donnees', 'is_admin': False,
                   'permissions': {c: (1 if c == 'alerts' else 3) for c in PERMISSION_CATEGORIES}},
        'viewer': {'description': 'Lecture seule', 'is_admin': False,
                   'permissions': {c: 1 for c in PERMISSION_CATEGORIES}},
    }
    created = False
    for name, cfg in defaults.items():
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name, description=cfg['description'],
                                is_admin=cfg['is_admin'], permissions=cfg['permissions']))
            created = True
    if created:
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
        print(f"  Identifiant : admin")
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
