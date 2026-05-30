"""Export total de secours (archive ZIP a mettre sur cle USB).

Contient : la base SQLite (restauration), les CSV de chaque domaine
(reexploitables), une page HTML de consultation (lisible hors-ligne, sans
l'application) et un LISEZMOI. Pensee pour un crash ou une attaque.
"""
import io
import os
import zipfile
import sqlite3
from datetime import datetime, timezone
from html import escape

from app import csv_io
from app.db_backup import _db_path

_LABELS = {'accounts': 'Comptes', 'certificates': 'Certificats',
           'domains': 'Domaines', 'backups': 'Backups', 'tests': 'Tests'}


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

A conserver sur un support hors-ligne (cle USB) en cas de crash ou d'attaque.
Ce fichier contient des informations sensibles : le proteger.
"""


def build_full_export(app):
    """Retourne (filename, bytes_zip)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for key in csv_io.SPECS:
            z.writestr(f'csv/{key}.csv', csv_io.export_csv(key))

        db_path = _db_path(app)
        if db_path and os.path.exists(db_path):
            con = sqlite3.connect(db_path)
            try:
                z.writestr('base/sentinelle.db', con.serialize())
            finally:
                con.close()

        z.writestr('consultation.html', _html_snapshot(app))
        z.writestr('LISEZMOI.txt', _README)

    buf.seek(0)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return f'sentinelle-export-{stamp}.zip', buf.getvalue()
