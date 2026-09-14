"""Sauvegarde automatique de la base SQLite de Sentinelle.

Utilise l'API de sauvegarde en ligne de sqlite3 (coherente meme si l'app
ecrit en parallele), avec horodatage et rotation (on garde les N plus recents).
"""
import os
import re
import glob
import sqlite3
from datetime import datetime, timezone

from app import db

_BACKUP_NAME_RE = re.compile(r'sentinelle_\d{8}_\d{6}\.db')


def _db_path(app):
    url = db.engine.url
    path = url.database
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(app.instance_path, path)
    return path


def _backup_dir(app):
    directory = app.config.get('BACKUP_DB_DIR') or os.path.join(app.instance_path, 'db_backups')
    os.makedirs(directory, exist_ok=True)
    return directory


def list_backups(app):
    """Liste des sauvegardes existantes, plus recentes d'abord."""
    directory = app.config.get('BACKUP_DB_DIR') or os.path.join(app.instance_path, 'db_backups')
    if not os.path.isdir(directory):
        return []
    files = glob.glob(os.path.join(directory, 'sentinelle_*.db'))
    infos = []
    for f in sorted(files, reverse=True):
        st = os.stat(f)
        infos.append({
            'name': os.path.basename(f),
            'size_kb': round(st.st_size / 1024, 1),
            'date': datetime.fromtimestamp(st.st_mtime),
        })
    return infos


def backup_database(app):
    """Cree une sauvegarde horodatee et applique la rotation. Retourne le chemin."""
    if not db.engine.url.get_backend_name().startswith('sqlite'):
        raise RuntimeError("Sauvegarde auto supportee uniquement pour SQLite.")
    src_path = _db_path(app)
    if not src_path or not os.path.exists(src_path):
        raise RuntimeError(f"Base introuvable : {src_path}")

    directory = _backup_dir(app)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    dest_path = os.path.join(directory, f'sentinelle_{stamp}.db')

    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    _rotate(app, directory)
    return dest_path


def delete_backup(app, name):
    """Supprime une sauvegarde de base par son nom (avec garde anti-traversee)."""
    if not name or not _BACKUP_NAME_RE.fullmatch(name):
        raise ValueError("Nom de sauvegarde invalide")
    directory = app.config.get('BACKUP_DB_DIR') or os.path.join(app.instance_path, 'db_backups')
    path = os.path.join(directory, name)
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(directory):
        raise ValueError("Chemin invalide")
    if not os.path.exists(path):
        raise ValueError("Sauvegarde introuvable")
    os.remove(path)


def _rotate(app, directory):
    keep = int(app.config.get('BACKUP_DB_KEEP', 14) or 14)
    files = sorted(glob.glob(os.path.join(directory, 'sentinelle_*.db')), reverse=True)
    for old in files[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass
