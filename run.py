import os
import sys

from app import create_app

app = create_app()

# --recharger-gabarits : les gabarits Jinja se relisent a chaque requete, sans
# redemarrer le serveur (apercu du bureau, .claude/launch.json). Le code Python,
# lui, demande toujours un redemarrage. Un argument et non une variable
# d'environnement : le .env est charge avec override=True et l'ecraserait.
if '--recharger-gabarits' in sys.argv:
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True

if __name__ == '__main__':
    # PORT (convention des outils de previsualisation et des PaaS) prime sur
    # APP_PORT : le .env est charge avec override=True, une variable
    # d'environnement ne peut donc pas le contourner autrement.
    port = int(os.environ.get('PORT') or app.config.get('APP_PORT', 5000))
    app.run(
        host=app.config.get('APP_HOST', '127.0.0.1'),
        port=port,
        debug=app.config.get('APP_DEBUG', False)
    )
