"""Assemble le sprite SVG des icones Lucide utilisees par le menu.

Sentinelle ne charge rien depuis Internet a l'execution : les icones sont
donc embarquees dans app/static/vendor/lucide.svg, un sprite de <symbol>
qu'un gabarit reference par <use href="...lucide.svg#nom">.

Le sprite ne contient QUE les icones listees ici (une vingtaine), pas les
1 500 de la bibliotheque : il pese quelques kilo-octets. Pour en ajouter
une, l'inscrire dans ICONES et relancer :

    .\\venv\\Scripts\\python.exe tools\\build_lucide_sprite.py

Source : le paquet lucide-static (licence ISC), via unpkg.
"""
import os
import re
import sys
import urllib.request

VERSION = '0.544.0'
SOURCE = f'https://unpkg.com/lucide-static@{VERSION}/icons/{{}}.svg'
DESTINATION = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'vendor', 'lucide.svg')

# Les noms Lucide, tels qu'ils apparaissent dans app/navigation.py.
# Les modeles sont ceux du menu de SoftInventory ; les entrees que
# SoftInventory n'avait pas (A venir, Domaines, Sauvegardes, Mises a jour,
# Revues, Alertes, Connecteurs, Corbeille) prennent l'icone Lucide la plus proche.
ICONES = [
    'layout-dashboard', 'calendar-days', 'chart-column', 'trash-2',
    'key-round', 'shield-check', 'globe', 'file-pen',
    'cloud-upload', 'clipboard-list', 'circle-arrow-up', 'user-check',
    'server', 'package', 'building',
    'bell', 'users', 'shield', 'notebook-text', 'calendar-clock', 'plug', 'sliders-horizontal',
    # Natures d'equipement (inventaire) : VM, serveur physique, NAS, baie, reseau, inconnu.
    'monitor', 'hard-drive', 'database', 'router', 'box',
    # Menu utilisateur (pied de la barre laterale).
    'user', 'log-out', 'chevron-down',
    # Rubriques de fiche (voir RUBRIQUES dans app/navigation.py).
    'paperclip', 'folder-open', 'info', 'flag', 'tag', 'tags',
    'lock-keyhole', 'badge-check', 'user-lock', 'id-card', 'user-cog', 'contact-round',
    'network', 'git-fork', 'calendar-check', 'calendar-range', 'refresh-cw',
    'coins', 'receipt', 'cpu', 'cloud', 'life-buoy', 'wrench', 'settings',
    # Actions en ligne sur une fiche : modifier, retirer une liaison.
    'pencil', 'square-pen', 'unlink', 'download', 'file-text', 'plus', 'upload',
    'arrow-right', 'arrow-left', 'copy', 'check',
]


def contenu(svg):
    """Ce qu'il y a entre <svg ...> et </svg> : les traces, sans l'enveloppe."""
    m = re.search(r'<svg[^>]*>(.*)</svg>', svg, re.S)
    if not m:
        raise ValueError('pas de <svg>')
    return m.group(1).strip()


def main():
    symboles = []
    for nom in ICONES:
        with urllib.request.urlopen(SOURCE.format(nom), timeout=20) as r:
            svg = r.read().decode('utf-8')
        # Les attributs de trait vont sur CHAQUE symbole : <use> ne clone que
        # le symbole, pas la racine du sprite, et sans eux les traces se
        # rempliraient de noir.
        symboles.append(f'  <symbol id="{nom}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">\n'
                        f'    {contenu(svg)}\n  </symbol>')
        print('  ok', nom)

    entete = (f'<!-- Icones Lucide {VERSION} (ISC), assemblees par tools/build_lucide_sprite.py.\n'
              '     Ne pas editer a la main : modifier ICONES et relancer le script. -->\n')
    sprite = (entete
              + '<svg xmlns="http://www.w3.org/2000/svg">\n'
              + '\n'.join(symboles) + '\n</svg>\n')
    with open(DESTINATION, 'w', encoding='utf-8', newline='\n') as f:
        f.write(sprite)
    print(f'{len(ICONES)} icones -> {os.path.normpath(DESTINATION)} ({len(sprite.encode())} octets)')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001 - message lisible plutot qu'une trace
        print('ERREUR :', e, file=sys.stderr)
        sys.exit(1)
