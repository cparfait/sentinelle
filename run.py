import os

from app import create_app

app = create_app()

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
