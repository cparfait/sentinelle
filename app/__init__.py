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
        from app.snooze import get_active_snooze, permission_category

        def role_label(name):
            labels = {'admin': 'Administrateur', 'editor': 'Éditeur', 'viewer': 'Lecteur'}
            return labels.get(name, (name or '').replace('-', ' ').replace('_', ' ').title())

        from markupsafe import Markup
        from app.theming import primary_css_override

        from app.features import all_flags
        return {'now': lambda: datetime.now(timezone.utc),
                'features': all_flags(),
                'active_snooze': get_active_snooze,
                'alert_permission': permission_category,
                'role_label': role_label,
                'ui_primary_css': lambda: Markup(primary_css_override(
                    app.config.get('UI_PRIMARY_COLOR', '')))}

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
                                Contract, Software)

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
                'software': _danger(Software.query.filter_by(is_active=True).all(), 'computed_status', 'software'),
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

    @app.context_processor
    def inject_navigation():
        """Menu et fil d'Ariane (app/navigation.py)."""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {}
        from app import navigation
        return navigation.contexte()

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

    from app.software import bp as software_bp
    app.register_blueprint(software_bp, url_prefix='/inventory/logiciels')

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

    from app.connectors import bp as connectors_bp
    app.register_blueprint(connectors_bp)

    from app.pdf_export import bp as pdf_export_bp
    app.register_blueprint(pdf_export_bp)

    from app.documents import bp as documents_bp
    app.register_blueprint(documents_bp)

    from app.referentials import bp as referentials_bp
    app.register_blueprint(referentials_bp)

    with app.app_context():
        _setup_sqlite()
        _drop_legacy_login_throttle()
        # AVANT create_all et l'ajout des colonnes : la table restauree doit
        # ensuite recevoir les colonnes manquantes comme n'importe quelle autre.
        _reprendre_certificat_interrompu()
        db.create_all()
        _auto_migrate_sqlite()
        _relacher_colonnes_certificat()
        _migrate_data()
        _migrate_roles()
        _seed_roles()
        _seed_referentials()
        _seed_default_user()
        # Configuration applicative persistee en base (messagerie, LDAP, seuils,
        # webhooks...). seed_from_env migre l'existant .env au 1er demarrage,
        # puis load() applique la base (source de verite) sur app.config.
        from app import config_store
        config_store.seed_from_env(app)
        config_store.load(app)

    @app.context_processor
    def inject_documents():
        """Ce dont `_documents.html` a besoin, partout ou il est inclus : rien a
        passer depuis chaque route qui l'affiche. Le partial est pose sur une
        dizaine de fiches, et faire porter le contexte par chacune n'aurait
        garanti qu'une chose : qu'on l'oublie sur la onzieme."""
        from flask_login import current_user
        from app.documents import (enabled, for_parent, viewable,
                                   inline_view_enabled, DEFAULT_MAX_MB)
        if not current_user.is_authenticated or not enabled():
            return {'documents_enabled': False}
        from app.models import Referential
        return {
            'documents_enabled': True,
            'attached_documents': for_parent,
            'document_viewable': viewable,
            'document_inline_view': inline_view_enabled(),
            'doc_categories': Referential.options('doc_category'),
            'document_max_mb': app.config.get('DOCUMENT_MAX_MB') or DEFAULT_MAX_MB,
        }

    # Vocabulaire unique des statuts et des délais (voir app/libelles.py) :
    # tout gabarit qui affiche une couleur ou un nombre de jours passe par là.
    from app import libelles
    app.jinja_env.filters['delai'] = libelles.delai
    app.jinja_env.filters['date_longue'] = libelles.date_longue
    app.jinja_env.filters['montant'] = libelles.montant
    app.jinja_env.globals.update(
        status_label=libelles.status_label,
        status_label_plural=libelles.status_label_plural,
        priority_label=libelles.priority_label,
        compte=libelles.compte,
        jours=libelles.jours,
        STATUS_LABELS=libelles.STATUS_LABELS,
    )

    @app.template_global()
    def equipment_kinds():
        """Les natures d'equipement, pour les listes deroulantes.

        Une variable GLOBALE et non une variable de contexte : les macros Jinja
        n'heritent pas du contexte du gabarit qui les appelle, et la fenetre
        d'ajout rapide en est une. Passer par le contexte obligerait a importer
        chaque macro « with context », et celui qu'on oublierait ne se verrait
        qu'a l'ouverture de la fenetre.
        """
        from app.models import EQUIPMENT_KIND_LABELS
        return EQUIPMENT_KIND_LABELS

    @app.template_global()
    def static_v(filename):
        """url_for('static') + version = date de modif du fichier. Force le
        navigateur a recharger un asset des qu'il change (fini le cache CSS/JS
        perime apres un deploiement)."""
        import os
        from flask import url_for
        try:
            v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return url_for('static', filename=filename, v=v)

    from app.navigation import lucide_de, couleur_icone
    app.jinja_env.globals['lucide_de'] = lucide_de
    app.jinja_env.globals['couleur_icone'] = couleur_icone

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
    # Hebergement : l'ancien booleen is_saas devient une valeur parmi trois
    # (on premise / SaaS / hybride). La colonne survit dans les bases existantes
    # -- SQLite ne sait pas la retirer sans reconstruire la table -- mais plus
    # rien ne la lit : on la verse une fois dans `hosting`, puis on l'oublie.
    from sqlalchemy import inspect as _inspect
    _cols = set()
    _tables = set()
    _ccols = set()
    try:
        _insp = _inspect(db.engine)
        _tables = set(_insp.get_table_names())
        _cols = {c['name'] for c in _insp.get_columns('software')}
        _ccols = {c['name'] for c in _insp.get_columns('contract')}
    except Exception:
        pass
    if 'is_saas' in _cols:
        db.session.execute(text(
            "UPDATE software SET hosting='saas' "
            "WHERE is_saas=1 AND (hosting IS NULL OR hosting='on_premise')"))
    db.session.execute(text(
        "UPDATE software SET hosting='on_premise' WHERE hosting IS NULL OR hosting=''"))
    db.session.execute(text(
        "UPDATE software SET lifecycle='production' WHERE lifecycle IS NULL OR lifecycle=''"))
    # Meme comblement pour les bases ou la table n'a pas eu besoin d'etre
    # reconstruite : une colonne ajoutee a chaud laisse le passe a NULL.
    db.session.execute(text(
        "UPDATE certificate SET kind='tls' WHERE kind IS NULL OR kind=''"))
    db.session.execute(text(
        "UPDATE certificate SET validity='valide' WHERE validity IS NULL OR validity=''"))
    # Les reglages du connecteur SoftInventory, retire : l'URL et la cle du
    # catalogue, la cle d'exposition du parc. `config_store.load()` ignore deja
    # ce qui n'est plus declare dans MANAGED -- ces lignes ne font donc rien de
    # mal, mais une cle d'API oubliee en base est une cle d'API de trop.
    db.session.execute(text(
        "DELETE FROM app_config WHERE key IN "
        "('SOFTINVENTORY_URL', 'SOFTINVENTORY_KEY', "
        " 'INVENTORY_API_ENABLED', 'INVENTORY_API_TOKEN')"))
    # Certificats TLS : le nom d'hote rejoint la fiche du domaine enregistre
    # dont il releve (www.mairie.fr -> mairie.fr). Ne touche qu'aux fiches
    # encore sans lien : un rattachement pose a la main n'est pas remis en cause.
    from app.models import Certificate, Domain
    for c in Certificate.query.filter(Certificate.kind == 'tls',
                                      Certificate.domain_id.is_(None),
                                      Certificate.domain.isnot(None)).all():
        d = Domain.for_host(c.domain)
        if d is not None:
            c.domain_id = d.id
    # Comptes : le nom du service rejoint la fiche logiciel ou equipement du
    # meme nom, quand UNE fiche active le porte, et seulement pour les comptes
    # encore sans aucun rattachement.
    for table, col in (('software', 'software_id'), ('equipment', 'equipment_id')):
        db.session.execute(text(
            f"UPDATE account SET {col} = ("
            f"  SELECT t.id FROM {table} t"
            f"  WHERE lower(t.name) = lower(account.service_name) AND t.is_active = 1)"
            f" WHERE software_id IS NULL AND equipment_id IS NULL AND supplier_id IS NULL AND ("
            f"  SELECT COUNT(*) FROM {table} t2"
            f"  WHERE lower(t2.name) = lower(account.service_name) AND t2.is_active = 1) = 1"))
    # Domaines : le bureau d'enregistrement saisi en texte rejoint la fiche
    # fournisseur du meme nom, quand UNE fiche active porte ce nom.
    db.session.execute(text(
        "UPDATE domain SET registrar_id = ("
        "  SELECT s.id FROM supplier s"
        "  WHERE lower(s.name) = lower(domain.registrar) AND s.is_active = 1)"
        " WHERE registrar_id IS NULL AND registrar IS NOT NULL AND ("
        "  SELECT COUNT(*) FROM supplier s2"
        "  WHERE lower(s2.name) = lower(domain.registrar) AND s2.is_active = 1) = 1"))
    # Revues de droits : l'application saisie en texte libre rejoint la fiche
    # logiciel du meme nom. Seulement quand UN logiciel actif porte ce nom :
    # deux homonymes, et l'on ne sait pas lequel la revue visait -- le lien
    # se posera a la main, le texte reste affiche entre-temps.
    db.session.execute(text(
        "UPDATE access_review SET software_id = ("
        "  SELECT s.id FROM software s"
        "  WHERE lower(s.name) = lower(access_review.application) AND s.is_active = 1)"
        " WHERE software_id IS NULL AND ("
        "  SELECT COUNT(*) FROM software s2"
        "  WHERE lower(s2.name) = lower(access_review.application) AND s2.is_active = 1) = 1"))
    # Contrats : l'ancien lien unique equipment_id est devenu une relation N:N
    # (table contract_equipment). La colonne n'est plus declaree ; si une base
    # ancienne l'a encore, on y recopie les liens une fois.
    if 'equipment_id' in _ccols:
        db.session.execute(text(
            "INSERT OR IGNORE INTO contract_equipment (contract_id, equipment_id) "
            "SELECT id, equipment_id FROM contract "
            "WHERE equipment_id IS NOT NULL"))
    # Mises a jour : la cible designee par son nom rejoint la fiche logiciel
    # ou equipement du meme nom, quand UNE fiche active le porte, pour les
    # lignes encore sans aucun lien.
    for table, col in (('software', 'software_id'), ('equipment', 'equipment_id')):
        db.session.execute(text(
            f"UPDATE system_update SET {col} = ("
            f"  SELECT t.id FROM {table} t"
            f"  WHERE lower(t.name) = lower(system_update.name) AND t.is_active = 1)"
            f" WHERE software_id IS NULL AND equipment_id IS NULL AND ("
            f"  SELECT COUNT(*) FROM {table} t2"
            f"  WHERE lower(t2.name) = lower(system_update.name) AND t2.is_active = 1) = 1"))
    # Marches : l'ancien lien unique Software.contract_id devient une relation
    # N:N (table contract_software). Un marche en couvre souvent plusieurs --
    # UGAP, marches communs a deux applications --, ce que la cle unique ne
    # savait pas dire. On y recopie les liens existants une fois. La colonne
    # survit dans les bases existantes, plus rien ne la lit.
    if 'contract_id' in _cols:
        db.session.execute(text(
            "INSERT OR IGNORE INTO contract_software (contract_id, software_id) "
            "SELECT contract_id, id FROM software WHERE contract_id IS NOT NULL"))
    # Les services utilisateurs ont quitte la table des libelles pour la leur :
    # ils portent un referent, avec son adresse. Les certificats qui pointaient
    # sur l'ancienne liste pointeraient desormais sur des identifiants d'une
    # autre table -- on les detache plutot que de laisser un rattachement faux,
    # et les lignes de l'ancienne liste s'en vont avec.
    db.session.execute(text(
        "UPDATE certificate SET service_id = NULL WHERE service_id IN "
        "(SELECT id FROM referential WHERE kind = 'user_service')"))
    db.session.execute(text("DELETE FROM referential WHERE kind = 'user_service'"))
    # Ancien catalogue « applications » des Preferences (table asset) ->
    # inventaire Logiciels. Le modele n'existe plus ; une base neuve n'a pas la
    # table, une base ancienne la garde, dormante, et la migration reste
    # idempotente (par nom).
    if 'asset' in _tables:
        db.session.execute(text(
            "INSERT INTO software (name, description, is_active, hosting, created_at, updated_at) "
            "SELECT a.name, a.description, 1, 'on_premise', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM asset a WHERE a.asset_type IN ('application') AND a.is_active=1 "
            "AND NOT EXISTS (SELECT 1 FROM software s WHERE s.name = a.name)"))
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
    """L'anti-bruteforce est passe d'une cle 'username' (unique) a un couple
    (username, ip). L'ancienne table porte une contrainte UNIQUE(username) qu'on
    ne peut pas retirer proprement en SQLite : on la supprime pour la laisser
    recreer au bon schema par create_all. Les compteurs d'echec sont ephemeres,
    leur remise a zero est sans consequence.

    On detecte le schema obsolete via la contrainte unique, PAS via la presence
    de la colonne 'ip' : _auto_migrate_sqlite a pu ajouter 'ip' lors d'un run
    precedent tout en laissant la contrainte UNIQUE(username) en place — ce qui
    faisait echouer le login des qu'un identifiant etait tente depuis une
    nouvelle IP (INSERT en doublon sur username)."""
    from sqlalchemy import inspect, text
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return
    insp = inspect(db.engine)
    if 'login_throttle' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('login_throttle')}
    try:
        unique_cols = [sorted(u.get('column_names') or [])
                       for u in insp.get_unique_constraints('login_throttle')]
    except Exception:
        unique_cols = []
    has_composite = ['ip', 'username'] in unique_cols
    stale_single = ['username'] in unique_cols
    if 'ip' not in cols or (stale_single and not has_composite):
        db.session.execute(text('DROP TABLE login_throttle'))
        db.session.commit()


def _reprendre_certificat_interrompu():
    """Rattrape une reconstruction de `certificate` interrompue en cours de route.

    Elle laisse les DEUX tables : la neuve, vide, et l'ancienne qui porte les
    donnees. On repart de l'ancienne plutot que de publier une table vide --
    une coupure ne doit rien couter. Ce rattrapage passe AVANT l'ajout des
    colonnes manquantes, pour que la table restauree soit remise a niveau comme
    n'importe quelle autre.
    """
    from sqlalchemy import inspect, text
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return
    if 'certificate_ancien' not in inspect(db.engine).get_table_names():
        return
    db.session.execute(text('DROP TABLE IF EXISTS certificate'))
    db.session.execute(text('ALTER TABLE certificate_ancien RENAME TO certificate'))
    db.session.commit()


# Les colonnes de `certificate` qui ont cesse d'etre obligatoires. Elles sont
# nommees ICI plutot que deduites du modele : la reconstruction d'une table est
# une operation trop lourde pour se declencher toute seule au gre d'un
# changement de modele, et la liste dit exactement ce qu'on a voulu relacher.
_CERT_A_RELACHER = ('domain', 'expiry_date')


def _relacher_colonnes_certificat():
    """Relache les NOT NULL devenus faux sur `certificate`.

    Le DOMAINE d'abord : un certificat electronique n'en a pas, sa date vient
    de l'autorite et non d'une poignee de main reseau. L'ECHEANCE ensuite : un
    certificat en cours de commande, ou dont personne n'a encore releve la
    date, existe quand meme.

    Le modele les dit nullables, mais SQLite ne sait pas relacher un NOT NULL
    sur une table existante -- il faut la reconstruire. Sans cela, l'insertion
    echoue sur une base ANTERIEURE, et seulement sur celle-la : le probleme ne
    se voit pas en test, ou la table nait au bon schema.

    La reconstruction passe par le MODELE plutot que par un CREATE TABLE
    recopie a la main : la table renait exactement comme create_all la ferait,
    et les colonnes ajoutees depuis ne sont pas oubliees. Les index sont
    recrees par _auto_migrate_sqlite au demarrage suivant, et les cles
    etrangeres qui pointent vers `certificate` ne sont pas contraintes ici
    (SQLite ne les applique que si on le lui demande).
    """
    from sqlalchemy import inspect, text
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        return
    insp = inspect(db.engine)
    if 'certificate' not in insp.get_table_names():
        return
    colonnes = {c['name']: c for c in insp.get_columns('certificate')}
    a_faire = [n for n in _CERT_A_RELACHER
               if n in colonnes and not colonnes[n].get('nullable', True)]
    if not a_faire:
        return   # deja relachees, ou table neuve

    # Les colonnes ajoutees A CHAUD ne remplissent pas les lignes EXISTANTES :
    # un defaut SQLAlchemy s'applique a l'insertion, pas au passe. `kind` et
    # `validity` y sont restes a NULL, et la table reconstruite les declare NOT
    # NULL -- la recopie echouerait sur la premiere ligne d'avant.
    db.session.execute(text(
        "UPDATE certificate SET kind='tls' WHERE kind IS NULL OR kind=''"))
    db.session.execute(text(
        "UPDATE certificate SET validity='valide' WHERE validity IS NULL OR validity=''"))
    db.session.commit()

    table = db.metadata.tables['certificate']
    communes = [c.name for c in table.columns if c.name in colonnes]
    liste = ', '.join(f'"{n}"' for n in communes)
    db.session.execute(text('ALTER TABLE certificate RENAME TO certificate_ancien'))
    # SQLite garde les INDEX attaches a la table renommee, sous leurs noms
    # d'origine : la recreer echouerait sur « index deja existant ». On les
    # retire d'abord ; _auto_migrate_sqlite les repose au demarrage suivant.
    anciens = db.session.execute(text(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='certificate_ancien' AND name NOT LIKE 'sqlite_%'")).scalars().all()
    for nom in anciens:
        db.session.execute(text(f'DROP INDEX "{nom}"'))
    db.session.commit()
    table.create(db.engine)
    db.session.execute(text(
        f'INSERT INTO certificate ({liste}) SELECT {liste} FROM certificate_ancien'))
    db.session.execute(text('DROP TABLE certificate_ancien'))
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


def _seed_referentials():
    """Verse les valeurs de depart des listes administrables, une seule fois par
    liste : on ne re-seme QUE si la liste est entierement vide.

    Ligne par ligne, on rendrait indefiniment une valeur que l'administrateur
    vient de supprimer -- et une liste se vide parfois exprès, pour la
    remplacer par celle de la collectivite."""
    from app.models import Referential, REFERENTIAL_SEEDS
    changed = False
    for kind, labels in REFERENTIAL_SEEDS.items():
        if Referential.query.filter_by(kind=kind).first() is not None:
            continue
        for i, label in enumerate(labels):
            db.session.add(Referential(kind=kind, label=label, position=i))
        changed = True
    if changed:
        db.session.commit()


def _migrate_roles():
    """Un droit nouveau-ne herite du droit qu'il remplace : « software » du
    niveau « inventory », « suppliers » du niveau « contracts ». Une seule fois
    (la cle absente le dit), pour que personne ne perde l'acces aux logiciels
    ni aux fournisseurs au redemarrage. Passe AVANT _seed_roles, qui sinon
    completerait les roles par defaut avec un niveau standard."""
    from app.models import Role, PERMISSION_INHERITANCE
    changed = False
    for role in Role.query.filter_by(is_admin=False).all():
        perms = dict(role.permissions or {})
        for nouveau, source in PERMISSION_INHERITANCE.items():
            if nouveau not in perms and source in perms:
                perms[nouveau] = perms[source]
                changed = True
        if perms != (role.permissions or {}):
            role.permissions = perms
    if changed:
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
