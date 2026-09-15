#!/usr/bin/env bash
# Deploiement de Sentinelle sur le serveur.
#
# Ce script existe parce que la sequence ne se devine pas, et qu'une erreur y
# est SILENCIEUSE. Le compose declare « image: sentinelle:local » sans section
# « build: » : « docker compose up --build » ne construit donc rien et ne s'en
# plaint pas. Et sans --force-recreate, Compose constate que le conteneur
# correspond toujours a la definition du service et le laisse tourner sur
# l'ancienne image. Dans les deux cas l'application repart, en bonne sante,
# avec le code de la veille — et rien ne le signale.
#
# D'ou la verification finale : on compare l'empreinte de l'image que porte le
# conteneur a celle du tag. Si elles divergent, on echoue bruyamment.
#
# Usage :  sudo ./scripts/deployer.sh
set -euo pipefail

DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG='sentinelle:local'
CONTENEUR='sentinelle_web'

cd "$DEPOT"

# Git appartient a l'utilisateur du depot, docker a root. Melanger les deux
# laisse des fichiers root dans un depot qui ne lui appartient pas, et le
# prochain « git pull » sans sudo echoue sur des permissions.
PROPRIO="$(stat -c '%U' "$DEPOT")"
git_depot() { sudo -u "$PROPRIO" git -C "$DEPOT" "$@"; }

echo "== Depot   : $DEPOT (proprietaire : $PROPRIO)"

# ── Garde-fous ──────────────────────────────────────────────────────────────
if [ ! -f "$DEPOT/.env" ]; then
    echo "ERREUR : .env absent. Il porte SECRET_KEY, qui dechiffre les secrets" >&2
    echo "         stockes en base (SMTP, LDAP, O365). N'en generez PAS un neuf :" >&2
    echo "         une clef differente rend ces secrets illisibles." >&2
    exit 1
fi

if [ -n "$(git_depot status --porcelain)" ]; then
    echo "ERREUR : modifications locales non validees. Le pull les ecraserait" >&2
    echo "         ou echouerait a mi-chemin :" >&2
    git_depot status --short >&2
    exit 1
fi

# ── Mise a jour du code ─────────────────────────────────────────────────────
AVANT_COMMIT="$(git_depot rev-parse --short HEAD)"
git_depot pull --ff-only
APRES_COMMIT="$(git_depot rev-parse --short HEAD)"
echo "== Code    : $AVANT_COMMIT -> $APRES_COMMIT"

# ── Construction ────────────────────────────────────────────────────────────
# L'empreinte d'avant sert de temoin : si elle ne bouge pas alors que le commit
# a change, c'est que le build n'a pas vu le nouveau code.
AVANT_IMAGE="$(docker image inspect "$TAG" --format '{{.Id}}' 2>/dev/null || echo 'aucune')"
docker build -t "$TAG" "$DEPOT"
APRES_IMAGE="$(docker image inspect "$TAG" --format '{{.Id}}')"

if [ "$AVANT_COMMIT" != "$APRES_COMMIT" ] && [ "$AVANT_IMAGE" = "$APRES_IMAGE" ]; then
    echo "ERREUR : le code a change mais l'image est identique ($APRES_IMAGE)." >&2
    echo "         Le build n'a pas pris le nouveau code — .dockerignore ?" >&2
    exit 1
fi

# ── Redemarrage ─────────────────────────────────────────────────────────────
docker compose up -d --force-recreate

# ── La verification qui compte ──────────────────────────────────────────────
IMAGE_CONTENEUR="$(docker inspect "$CONTENEUR" --format '{{.Image}}')"
if [ "$IMAGE_CONTENEUR" != "$APRES_IMAGE" ]; then
    echo "ERREUR : le conteneur tourne sur $IMAGE_CONTENEUR," >&2
    echo "         alors que $TAG vaut $APRES_IMAGE." >&2
    echo "         Reparer par :  docker rm -f $CONTENEUR && docker compose up -d" >&2
    exit 1
fi

# Les montages : la base SQLite, le jeton O365 et l'autorite de certification du
# LDAP vivent sur l'hote. Un montage perdu ne se voit pas au demarrage — il se
# voit au premier envoi de mail, ou a la premiere connexion annuaire.
echo "== Montages :"
docker inspect "$CONTENEUR" --format '{{range .Mounts}}   {{.Source}} -> {{.Destination}}{{println}}{{end}}'

# ── Demarrage ───────────────────────────────────────────────────────────────
sleep 5
if docker logs --tail 50 "$CONTENEUR" 2>&1 | grep -q 'Dechiffrement config echoue'; then
    echo "ATTENTION : des secrets ne se dechiffrent plus. SECRET_KEY a change ?" >&2
    echo "            Les mots de passe SMTP / LDAP / O365 sont a ressaisir." >&2
fi
docker logs --tail 10 "$CONTENEUR" 2>&1 | sed 's/^/   /'

echo
echo "== Deploye : $APRES_COMMIT sur $APRES_IMAGE"
echo "   Pensez au Ctrl+F5 : le CSS est servi depuis le cache du navigateur."
