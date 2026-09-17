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


# Connexion automatique en admin : la base est jetable, on vient regarder l'UI,
# pas taper un mot de passe a chaque redemarrage.
@app.before_request
def _preview_auto_login():
    from flask_login import current_user, login_user
    from app.models import User
    from flask import request
    # La page de connexion reste visible telle quelle (pour la regarder).
    if request.path == '/login':
        return
    if not current_user.is_authenticated:
        admin = next((u for u in User.query.all() if u.is_admin), None)
        if admin:
            login_user(admin)

if __name__ == '__main__':
    assert 'ui_preview' in app.config['SQLALCHEMY_DATABASE_URI'], \
        'Garde-fou : la preview doit pointer sur ui_preview.db'
    # PORT : pose par l'apercu du bureau quand 5099 est deja pris par une
    # autre session ; 5099 reste le defaut en ligne de commande.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT') or 5099),
            debug=False, use_reloader=False)
