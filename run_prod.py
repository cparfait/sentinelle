"""Lancement de Sentinelle en PRODUCTION via le serveur WSGI waitress.

Pourquoi : `run.py` utilise le serveur de developpement Flask (non adapte a la
production). waitress est un serveur WSGI pur Python, fiable, simple sur Windows.

Important : le planificateur d'alertes (APScheduler) tourne DANS le process.
waitress fonctionne en UN SEUL process (multi-threads), ce qui garantit que le
planificateur ne s'execute qu'une fois (pas d'alertes en double). Ne pas lancer
plusieurs instances/process en parallele.

Usage :
    .\\venv\\Scripts\\python.exe run_prod.py

Pre-requis dans .env : SECRET_KEY fort, APP_DEBUG=false, APP_HOST, APP_PORT.
"""
from waitress import serve
from app import create_app

app = create_app()

if __name__ == '__main__':
    host = app.config.get('APP_HOST', '0.0.0.0')
    port = int(app.config.get('APP_PORT', 5000))
    threads = int(__import__('os').getenv('WAITRESS_THREADS', 8))
    print(f'Sentinelle (production / waitress) -> http://{host}:{port} ({threads} threads)')
    serve(app, host=host, port=port, threads=threads)
