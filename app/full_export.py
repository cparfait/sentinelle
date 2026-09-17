"""Export total de secours (archive ZIP a mettre sur cle USB).

Contient : la base SQLite (restauration), les CSV de chaque domaine
(reexploitables), une page HTML de consultation (lisible hors-ligne, sans
l'application) et un LISEZMOI. Pensee pour un crash ou une attaque.

── Sur disque, jamais en memoire ──

L'archive s'ecrit dans un FICHIER TEMPORAIRE, et la base y entre en flux.
L'ancienne version tenait le ZIP dans un BytesIO et lisait la base d'un bloc
(`serialize()`) : c'etait sans consequence tant que la base pesait quelques
mega-octets, et c'est devenu un risque d'epuisement memoire le jour ou les
pieces jointes l'ont fait passer a plusieurs centaines. Le cout d'un export ne
doit pas dependre de ce qu'on a mis dedans.

── Avec ou sans les pieces jointes ──

`sans_documents` retire les OCTETS des pieces jointes de la copie exportee :
quelques centaines de mega-octets tombent a quelques centaines de kilo-octets.
Les fiches de documents restent, leur contenu non — une archive allegee ne
remplace donc pas une complete, elle s'intercale entre deux.
"""
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from html import escape

from app import csv_io
from app.db_backup import _db_path

_LABELS = {'accounts': 'Comptes', 'certificates': 'Certificats',
           'domains': 'Domaines', 'backups': 'Sauvegardes', 'tests': 'Tests',
           'reviews': 'Revue de droits', 'updates': 'Mises à jour'}


def _html_snapshot(app):
    now = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
    blocks = []
    for key, spec in csv_io.SPECS.items():
        rows = spec['model'].query.filter_by(is_active=True).all()
        cols = spec['columns']
        head = ''.join(f'<th>{escape(c)}</th>' for c, _ in cols)
        body = ''
        for r in rows:
            cells = ''.join(
                f'<td>{escape(csv_io._fmt(getattr(r, c), k))}</td>' for c, k in cols)
            body += f'<tr>{cells}</tr>'
        if not rows:
            body = f'<tr><td colspan="{len(cols)}" class="muted">Aucun</td></tr>'
        blocks.append(
            f'<h2>{escape(_LABELS.get(key, key))} '
            f'<span class="muted">({len(rows)})</span></h2>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')
    return (
        '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
        '<title>Sentinelle — export de consultation</title><style>'
        'body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1e293b;}'
        'h1{color:#4f46e5;} h2{margin-top:28px;border-bottom:2px solid #e2e8f0;padding-bottom:4px;}'
        'table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px;}'
        'th,td{border:1px solid #e2e8f0;padding:6px 8px;text-align:left;}'
        'th{background:#f1f5f9;} .muted{color:#94a3b8;font-weight:normal;}'
        '</style></head><body>'
        f'<h1>&#128737; Sentinelle — Export de consultation</h1>'
        f'<p class="muted">Genere le {now}. Donnees actives uniquement.</p>'
        + ''.join(blocks) +
        '</body></html>'
    )


_README = """SENTINELLE — EXPORT TOTAL DE SECOURS
=====================================

Contenu de cette archive :

  consultation.html   Page consultable dans un navigateur, SANS l'application
                      ni la base (a ouvrir directement). Vue d'ensemble des
                      comptes, certificats, domaines, backups et tests.

  csv/                Les donnees au format CSV (Excel / LibreOffice),
                      reimportables dans Sentinelle (bouton CSV des listes).

  base/sentinelle.db  Copie complete de la base SQLite. Pour restaurer :
                      arreter Sentinelle, remplacer le fichier de base par
                      celui-ci (instance/admin_dashboard.db), redemarrer.
                      ATTENTION : dans une archive ALLEGEE, cette base ne
                      contient pas les octets des pieces jointes. Leurs fiches
                      sont la, les telechargements repondraient 404.

A conserver sur un support hors-ligne (cle USB) en cas de crash ou d'attaque.
Ce fichier contient des informations sensibles : le proteger.
"""


def _copie_coherente(app, destination, sans_documents=False):
    """Une copie de la base, prise par l'API `backup` de SQLite.

    Un `shutil.copy` sur une base en cours d'ecriture donnerait un fichier
    incoherent (le journal WAL vit a cote) ; l'API backup, elle, produit un
    fichier autonome et valide meme sous ecriture. C'est deja ce que fait la
    sauvegarde automatique quotidienne.
    """
    source = _db_path(app)
    if not source or not os.path.exists(source):
        return False
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        with dst:
            src.backup(dst)
        if sans_documents:
            # Sur la COPIE, jamais sur la base vivante. VACUUM rend la place
            # au fichier : sans lui, l'archive pese autant qu'avant et
            # l'allegement ne servirait a rien.
            dst.execute('DELETE FROM document_content')
            dst.commit()
            dst.execute('VACUUM')
    finally:
        src.close()
        dst.close()
    return True


# Prefixe des repertoires de travail : il sert aussi a les RETROUVER pour les
# balayer. Un nom sans prefixe rendrait le nettoyage impossible sans tenir une
# liste, et une liste tenue en memoire ne survit pas a un redemarrage.
_PREFIXE = 'sentinelle-export-'

# Au-dela, un repertoire de travail est un RESTE : l'export qui l'a cree est
# fini depuis longtemps, abouti ou non.
_PEREMPTION_S = 3600


def _balayer_restes():
    """Supprime les repertoires de travail abandonnes.

    La suppression apres envoi est du MEILLEUR EFFORT : elle s'accroche a la
    fermeture de la reponse, qui n'arrive pas si le client coupe, si le process
    est tue, ou si le serveur redemarre en cours d'envoi. Un ZIP de plusieurs
    centaines de mega-octets oublie a chaque fois finirait par remplir le
    disque. Le balayage rend le nettoyage certain, meme en retard.
    """
    import time
    racine = tempfile.gettempdir()
    limite = time.time() - _PEREMPTION_S
    try:
        entrees = os.listdir(racine)
    except OSError:
        return
    for nom in entrees:
        if not nom.startswith(_PREFIXE):
            continue
        chemin = os.path.join(racine, nom)
        try:
            if os.path.isdir(chemin) and os.path.getmtime(chemin) < limite:
                shutil.rmtree(chemin, ignore_errors=True)
        except OSError:
            # Un reste qu'on n'arrive pas a lire attendra le prochain passage :
            # echouer ici ferait echouer un export qui n'a rien a se reprocher.
            continue


def build_full_export(app, sans_documents=False):
    """Construit l'archive et retourne (filename, chemin_du_zip).

    Le fichier rendu est TEMPORAIRE : l'appelant l'envoie puis le supprime
    (cf. `data_io.export_full`). On rend un chemin plutot que des octets pour
    que l'archive ne transite jamais en entier par la memoire.
    """
    _balayer_restes()
    travail = tempfile.mkdtemp(prefix=_PREFIXE)
    base_copie = os.path.join(travail, 'sentinelle.db')
    zip_path = os.path.join(travail, 'archive.zip')
    try:
        avec_base = _copie_coherente(app, base_copie, sans_documents)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for key in csv_io.SPECS:
                z.writestr(f'csv/{key}.csv', csv_io.export_csv(key))
            if avec_base:
                # `z.write` lit le fichier par blocs : la base n'est jamais
                # chargee en entier, quelle que soit sa taille.
                z.write(base_copie, 'base/sentinelle.db')
            z.writestr('consultation.html', _html_snapshot(app))
            z.writestr('LISEZMOI.txt', _README)
    except Exception:
        shutil.rmtree(travail, ignore_errors=True)
        raise
    finally:
        # La copie de travail ne sert plus des qu'elle est dans l'archive.
        if os.path.exists(base_copie):
            os.remove(base_copie)

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    allege = '-sans-documents' if sans_documents else ''
    return f'sentinelle-export-{stamp}{allege}.zip', zip_path
