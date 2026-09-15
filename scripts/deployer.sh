#!/usr/bin/env bash
# Construction de l'image Sentinelle, en amont d'un redeploiement Portainer.
#
# PARTAGE DES ROLES : ce script construit, PORTAINER deploie.
#
# Portainer detient la pile (projet « sentinelle », sa propre copie du
# docker-compose.yml dans son volume). Recreer le conteneur en ligne de commande
# lui passerait devant, et son prochain « redeploy » defairait le travail. Le
# script s'arrete donc apres le build et vous rend la main.
#
# Deux pieges, tous deux SILENCIEUX, que ce script eclaire :
#
#   1. L'image « sentinelle:local » est construite ICI et n'existe dans aucun
#      registre. Dans Portainer, ne cochez JAMAIS « Re-pull image » : le pull
#      echoue sur « pull access denied », et rien n'est deploye.
#
#   2. Portainer travaille sur une COPIE du compose, prise le jour ou la pile a
#      ete creee. Elle ne suit pas le depot. Si docker-compose.yml change ici,
#      il faut le recopier dans l'editeur de Portainer — sinon un redeploiement
#      appliquera une definition perimee (montages, variables d'alors).
#      Le script previent quand ce fichier a change.
#
# Usage :  sudo ./scripts/deployer.sh
set -euo pipefail

DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG='sentinelle:local'
CONTENEUR='sentinelle_web'
COMPOSE='docker-compose.yml'

cd "$DEPOT"

# Git appartient a l'utilisateur du depot, docker a root. Melanger les deux
# laisse des fichiers root dans un depot qui ne lui appartient pas, et le
# prochain « git pull » sans sudo echoue sur des permissions.
PROPRIO="$(stat -c '%U' "$DEPOT")"
git_depot() { sudo -u "$PROPRIO" git -C "$DEPOT" "$@"; }

echo "== Depot   : $DEPOT (proprietaire : $PROPRIO)"

# ── Garde-fous ──────────────────────────────────────────────────────────────
if [ -n "$(git_depot status --porcelain)" ]; then
    echo "ERREUR : modifications locales non validees. Le pull les ecraserait" >&2
    echo "         ou echouerait a mi-chemin :" >&2
    git_depot status --short >&2
    exit 1
fi

# ── Mise a jour du code ─────────────────────────────────────────────────────
AVANT_COMMIT="$(git_depot rev-parse HEAD)"
git_depot pull --ff-only
APRES_COMMIT="$(git_depot rev-parse HEAD)"
echo "== Code    : $(git_depot rev-parse --short "$AVANT_COMMIT") -> $(git_depot rev-parse --short "$APRES_COMMIT")"

# Le compose a-t-il bouge ? Portainer n'en saura rien tout seul.
COMPOSE_MODIFIE='non'
if [ "$AVANT_COMMIT" != "$APRES_COMMIT" ] \
   && ! git_depot diff --quiet "$AVANT_COMMIT" "$APRES_COMMIT" -- "$COMPOSE"; then
    COMPOSE_MODIFIE='oui'
fi

# ── Construction ────────────────────────────────────────────────────────────
# BuildKit lit le depot pour etiqueter l'image du commit dont elle vient. Git
# le lui refuse — l'utilisateur qui construit (root) n'est pas proprietaire du
# depot — et le build se poursuit en avertissant a chaque passage :
#   « current commit information was not captured by the build »
#
# On autorise donc cette LECTURE. La reserve habituelle sur safe.directory vise
# les ECRITURES : un « git pull » lance par root deposerait des fichiers root
# dans un depot appartenant a quelqu'un d'autre, et le prochain pull sans sudo
# echouerait sur des permissions. Ici toutes les commandes git passent par
# git_depot(), donc par le proprietaire ; seul BuildKit lit.
#
# Idempotent : on n'ajoute la ligne que si elle manque, sinon elle s'empilerait
# a chaque deploiement.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "$DEPOT"; then
    git config --global --add safe.directory "$DEPOT"
    echo "== Git     : lecture du depot autorisee pour $(id -un) (safe.directory)"
fi

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
echo "== Image   : $APRES_IMAGE"

# ── Le conteneur tourne-t-il deja dessus ? ──────────────────────────────────
IMAGE_CONTENEUR="$(docker inspect "$CONTENEUR" --format '{{.Image}}' 2>/dev/null || echo 'aucun')"

echo
if [ "$COMPOSE_MODIFIE" = 'oui' ]; then
    echo "!! $COMPOSE A CHANGE dans ce pull."
    echo "   Recopiez-le dans Portainer (Stacks > sentinelle > Editor) AVANT de"
    echo "   redeployer, sinon la definition perimee de Portainer s'appliquera."
    echo
fi

if [ "$IMAGE_CONTENEUR" = "$APRES_IMAGE" ]; then
    echo "== Rien a faire : $CONTENEUR tourne deja sur cette image."
    docker inspect "$CONTENEUR" --format '   {{.State.Status}} depuis {{.State.StartedAt}}'
    exit 0
fi

cat <<FIN
== A FAIRE dans Portainer

   Stacks > sentinelle > Update the stack
   NE COCHEZ PAS « Re-pull image » : l'image est locale, le pull echouerait.

   Le conteneur tourne sur $IMAGE_CONTENEUR
   L'image fraiche est   $APRES_IMAGE

   Relancez ce script ensuite : il verifiera que le conteneur a bien pris la
   nouvelle image. Sans cette verification, un redeploiement sans effet laisse
   l'application en bonne sante sur le code de la veille, sans rien signaler.

   Puis Ctrl+F5 dans le navigateur : le CSS vient du cache.
FIN
