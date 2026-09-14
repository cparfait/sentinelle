#!/usr/bin/env bash
# Telecharge les .woff2 IBM Plex (Sans 400/500/600/700, Mono 500/600) dans CE
# dossier. A lancer UNE fois sur une machine connectee. App 100% hors-ligne ensuite.
#   chmod +x download-fonts.sh && ./download-fonts.sh
set -e
cd "$(dirname "$0")"
cdn="https://cdn.jsdelivr.net/npm"

dl() { curl -fsSL "$1" -o "$2" && echo "OK  $2"; }

dl "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-400-normal.woff2" "ibm-plex-sans-latin-400-normal.woff2"
dl "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-500-normal.woff2" "ibm-plex-sans-latin-500-normal.woff2"
dl "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-600-normal.woff2" "ibm-plex-sans-latin-600-normal.woff2"
dl "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-700-normal.woff2" "ibm-plex-sans-latin-700-normal.woff2"
dl "$cdn/@fontsource/ibm-plex-mono@5/files/ibm-plex-mono-latin-500-normal.woff2" "ibm-plex-mono-latin-500-normal.woff2"
dl "$cdn/@fontsource/ibm-plex-mono@5/files/ibm-plex-mono-latin-600-normal.woff2" "ibm-plex-mono-latin-600-normal.woff2"

echo ""
echo "Termine. Les 6 .woff2 sont dans $(pwd)"
