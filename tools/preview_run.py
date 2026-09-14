"""Lance Sentinelle sur une base jetable pour previsualiser l'UI.

ATTENTION : config.py fait load_dotenv(override=True), donc le .env ecrase les
variables d'environnement. On ne passe PAS par DATABASE_URL : la base de
previsualisation est imposee via une classe de config dediee, immunisee contre
le .env. La vraie base (instance/admin_dashboard.db) n'est jamais touchee.

Usage : python tools/preview_run.py
  -> http://127.0.0.1:5099, admin / Preview-2026! (premier demarrage)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lu par _seed_default_user() au premier demarrage sur base vierge (os.getenv
# direct ; pas dans le .env, donc pas ecrase par load_dotenv).
os.environ['ADMIN_INITIAL_PASSWORD'] = 'Preview-2026!'

from config import Config  # noqa: E402
from app import create_app  # noqa: E402


class PreviewConfig(Config):
    # Chemin relatif -> resolu dans instance/ par Flask-SQLAlchemy.
    SQLALCHEMY_DATABASE_URI = 'sqlite:///ui_preview.db'
    SECRET_KEY = 'ui-preview-secret-key-not-for-prod'
    # Desactive le scheduler : pas d'alertes/mails declenches par la preview.
    TESTING = True
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0


app = create_app(PreviewConfig)
app.jinja_env.auto_reload = True

if __name__ == '__main__':
    assert 'ui_preview' in app.config['SQLALCHEMY_DATABASE_URI'], \
        'Garde-fou : la preview doit pointer sur ui_preview.db'
    app.run(host='127.0.0.1', port=5099, debug=False, use_reloader=False)
