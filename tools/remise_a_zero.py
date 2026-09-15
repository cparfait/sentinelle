"""Vide les données métier d'une base Sentinelle, en gardant sa CONFIGURATION.

À quoi ça sert : repartir d'une base propre sans reperdre ce qui a été patiemment
réglé — l'annuaire AD, la messagerie, les seuils d'alerte, les rôles et les
comptes. Utile pour une remise à plat, pour préparer une reprise de données, ou
pour se refaire une base d'essai réaliste.

── Usage ──

    .\\venv\\Scripts\\python.exe tools\\remise_a_zero.py --essai
    .\\venv\\Scripts\\python.exe tools\\remise_a_zero.py

`--essai` compte ce qui serait effacé sans rien toucher. `--base <chemin>` vise
une autre base que celle de `.env` ; c'est le cas ordinaire quand on remet à
plat une copie rapatriée d'un serveur.

── Pourquoi une liste de ce qu'on GARDE ──

Et non de ce qu'on efface. Une liste d'effacement vieillit mal : le jour où un
module ajoute une table, personne ne pense à l'y inscrire, et la « remise à
zéro » laisse derrière elle des données que plus rien ne montre. Ici, tout ce
qui n'est pas nommé s'en va — un module nouveau est vidé sans qu'on ait rien à
faire, et c'est bien ce qu'on attend d'une remise à zéro.

── Les secrets ne bougent pas ──

`app_config` est conservée TELLE QUELLE, y compris les valeurs chiffrées (mot de
passe SMTP, secret O365, mot de passe du compte de service LDAP). Elles restent
chiffrées avec la SECRET_KEY de l'instance d'origine : une base remise à plat
ici puis renvoyée là-bas retrouve donc des secrets qui fonctionnent, sans avoir
eu besoin de les lire au passage.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ce qui SURVIT à la remise à zéro. Tout le reste est vidé.
CONFIGURATION = {
    'app_config',   # messagerie, LDAP, seuils, webhooks — secrets compris
    'setting',      # réglages divers (table historique)
    'role',         # rôles et matrice de permissions
    'user',         # les comptes, sans lesquels on ne se reconnecte pas
}

# Le parc appartient à Sentinelle : SoftInventory n'en gardait qu'une référence,
# et le ressaisir coûte des heures. On le garde par défaut ; `--sans-parc` le
# vide aussi.
PARC = {'equipment'}


def _tables_a_vider(metadata, garder_parc):
    garde = CONFIGURATION | (PARC if garder_parc else set())
    # Ordre INVERSE des dépendances : les tables qui pointent vers d'autres
    # partent en premier. SQLite n'applique pas les clés étrangères par défaut,
    # mais s'en remettre à cela rendrait le script faux le jour où on l'active.
    return [t.name for t in reversed(metadata.sorted_tables) if t.name not in garde]


def main():
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--base', help='Chemin de la base SQLite à remettre à plat')
    ap.add_argument('--essai', action='store_true',
                    help="Compte ce qui serait effacé, sans rien toucher")
    ap.add_argument('--sans-parc', action='store_true',
                    help="Vide aussi l'inventaire du parc (équipements)")
    args = ap.parse_args()

    from sqlalchemy import text

    from config import Config
    from app import create_app, db

    class C(Config):
        pass
    if args.base:
        C.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.abspath(args.base)

    # create_app AVANT tout : il met le schéma à niveau (colonnes manquantes,
    # reconstruction de la table certificate). Vider une base au schéma d'hier
    # laisserait un schéma d'hier.
    app = create_app(C)
    with app.app_context():
        tables = _tables_a_vider(db.metadata, garder_parc=not args.sans_parc)
        vidées = {}
        for nom in tables:
            try:
                n = db.session.execute(text(f'SELECT count(*) FROM "{nom}"')).scalar()
            except Exception:
                continue        # table absente de cette base : rien à vider
            if not n:
                continue
            vidées[nom] = n
            if not args.essai:
                db.session.execute(text(f'DELETE FROM "{nom}"'))
        if not args.essai:
            # Les compteurs d'auto-incrément repartent de 1 : une base remise à
            # zéro dont les identifiants commencent à 4 200 n'est pas remise à
            # zéro, elle est seulement vide.
            try:
                db.session.execute(text('DELETE FROM sqlite_sequence'))
            except Exception:
                pass
            db.session.commit()
            db.session.execute(text('VACUUM'))
            db.session.commit()

        gardées = {}
        garde = CONFIGURATION | (set() if args.sans_parc else PARC)
        for nom in sorted(garde):
            try:
                gardées[nom] = db.session.execute(
                    text(f'SELECT count(*) FROM "{nom}"')).scalar()
            except Exception:
                pass

    print()
    print('== Remise à zéro ' + ('(ESSAI, rien effacé) ' if args.essai else '') + '=' * 28)
    print('  Base :', app.config['SQLALCHEMY_DATABASE_URI'])
    print()
    print('  GARDÉ')
    for nom, n in gardées.items():
        print(f'    {n:>6}  {nom}')
    print()
    print('  EFFACÉ' if not args.essai else '  À EFFACER')
    if not vidées:
        print('         —  rien à effacer')
    for nom, n in sorted(vidées.items()):
        print(f'    {n:>6}  {nom}')
    print()


if __name__ == '__main__':
    main()
