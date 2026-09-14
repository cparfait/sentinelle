# Telecharge les .woff2 IBM Plex (Sans 400/500/600/700, Mono 500/600) dans CE
# dossier, au nom attendu par ibm-plex.css. A lancer UNE fois sur une machine
# connectee. Ensuite l'app fonctionne 100% hors-ligne.
#
# Usage : clic droit > "Executer avec PowerShell", ou :
#   powershell -ExecutionPolicy Bypass -File .\DOWNLOAD-FONTS.ps1

$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$cdn = 'https://cdn.jsdelivr.net/npm'

$files = @(
  @{ url = "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-400-normal.woff2"; name = 'ibm-plex-sans-latin-400-normal.woff2' },
  @{ url = "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-500-normal.woff2"; name = 'ibm-plex-sans-latin-500-normal.woff2' },
  @{ url = "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-600-normal.woff2"; name = 'ibm-plex-sans-latin-600-normal.woff2' },
  @{ url = "$cdn/@fontsource/ibm-plex-sans@5/files/ibm-plex-sans-latin-700-normal.woff2"; name = 'ibm-plex-sans-latin-700-normal.woff2' },
  @{ url = "$cdn/@fontsource/ibm-plex-mono@5/files/ibm-plex-mono-latin-500-normal.woff2"; name = 'ibm-plex-mono-latin-500-normal.woff2' },
  @{ url = "$cdn/@fontsource/ibm-plex-mono@5/files/ibm-plex-mono-latin-600-normal.woff2"; name = 'ibm-plex-mono-latin-600-normal.woff2' }
)

foreach ($f in $files) {
  $out = Join-Path $dir $f.name
  Invoke-WebRequest -Uri $f.url -OutFile $out
  Write-Host ("OK  " + $f.name)
}
Write-Host "`nTermine. Les 6 .woff2 sont dans $dir"
