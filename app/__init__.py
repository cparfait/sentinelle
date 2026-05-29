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
        return {'now': lambda: datetime.now(timezone.utc)}

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

    with app.app_context():
        db.create_all()
        _seed_default_user()

    from app.scheduler import start_scheduler
    if not app.config.get('TESTING'):
        start_scheduler(app)

    return app


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
