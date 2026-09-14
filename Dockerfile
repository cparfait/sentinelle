# ============================================================================
#  Sentinelle — image applicative (Flask + waitress + APScheduler, base SQLite)
#
#  UN SEUL conteneur, UN SEUL process : le planificateur d'alertes tourne DANS
#  l'application (APScheduler, cf. run_prod.py). Ne jamais monter a plusieurs
#  replicas ni passer a un serveur multi-process (gunicorn -w N) : chaque
#  process rejouerait les jobs et les alertes partiraient en double.
#
#  Le code vit dans /app/sentinelle et NON dans /app : app/email_service.py
#  ecrit le jeton O365 dans le PARENT de la racine du projet, soit
#  /app/o365_token.json. Ce niveau intermediaire permet de le persister sans
#  recouvrir le code par un volume.
# ============================================================================
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Paris

# tzdata : les jobs quotidiens (alertes 08h00, sauvegarde 01h00, CT 06h30) se
# declenchent a l'heure locale — sans tzdata le conteneur vit en UTC.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/sentinelle

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Utilisateur non privilegie. Les deux emplacements ecrits a chaud :
#   /app/sentinelle/instance  base SQLite, journaux, sauvegardes auto
#   /app/o365_token.json      jeton OAuth2 Microsoft Graph (chiffre)
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin sentinelle \
 && mkdir -p /app/sentinelle/instance \
 && chown -R sentinelle:sentinelle /app

USER sentinelle

EXPOSE 5000

# /health interroge la base : un conteneur « healthy » signifie app + SQLite OK.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=5).status == 200 else 1)"

# waitress (multi-threads, mono-process) — cf. run_prod.py.
CMD ["python", "run_prod.py"]
