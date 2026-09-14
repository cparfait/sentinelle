"""Analyse d'un mail recap de backup et enregistrement automatique des checks.

Heuristique v1, volontairement tolerante : pour chaque sauvegarde active, on
cherche les lignes du mail qui mentionnent son nom de service, puis on en deduit
le statut a partir de mots-cles. A affiner avec un vrai exemple de recap.
"""
import os
import re
import glob
import shutil
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser

from app import db
from app.models import Backup, BackupCheck, BackupHistory

# Detection par MOTS ENTIERS (\b) pour eviter les faux positifs comme "Ko"
# (kilo-octets) qui matcherait "ko", ou "ok" dans un autre mot.
_RE_FAIL = re.compile(r'\b(failed|failure|fail|echec|échec|erreur|error|aborted|'
                      r'interrompu|unsuccessful)\b', re.IGNORECASE)
_RE_WARN = re.compile(r'\b(warning|avertissement|partial|partiel)\b', re.IGNORECASE)
_RE_SUCCESS = re.compile(r'\b(success|succes|succès|reussi|réussi|completed|'
                         r'complete|terminé|termine)\b', re.IGNORECASE)
# Tag de statut entre crochets dans l'objet (format Veeam : [Success]/[Warning]/[Failed])
_RE_BRACKET = re.compile(r'\[\s*(success|succès|succes|ok|warning|avertissement|'
                         r'failed|failure|error|erreur|echec|échec)\s*\]', re.IGNORECASE)


def _map_bracket(word):
    w = word.lower()
    if w in ('failed', 'failure', 'error', 'erreur', 'echec', 'échec'):
        return 'failed'
    if w in ('warning', 'avertissement'):
        return 'warning'
    return 'ok'


def _detect_status(subject, body):
    """Statut global deduit d'un mail (un mail = un compte-rendu de backup)."""
    subject = subject or ''
    text = f"{subject}\n{body or ''}"
    # 1) tag entre crochets dans l'objet (Veeam) — signal le plus fiable
    m = _RE_BRACKET.search(subject)
    if m:
        return _map_bracket(m.group(1))
    # 2) mots-cles explicites dans tout le texte (echec > avertissement > succes)
    if _RE_FAIL.search(text):
        return 'failed'
    if _RE_WARN.search(text):
        return 'warning'
    if _RE_SUCCESS.search(text):
        return 'ok'
    return None


def parse_and_record(subject, body, source='mail'):
    """Enregistre le check du jour pour les backups mentionnes dans le mail.
    Un mail correspond a un compte-rendu (Veeam, script de sauvegarde...).
    Retourne la liste [{'backup':.., 'status':..}] des backups mis a jour."""
    today = datetime.now(timezone.utc).date()
    subject = subject or ''
    body = body or ''
    subject_l = subject.lower()
    text_l = f"{subject}\n{body}".lower()
    base_status = _detect_status(subject, body)

    results = []
    for b in Backup.query.filter_by(is_active=True).all():
        name = (b.service_name or '').strip().lower()
        if not name or name not in text_l:
            continue
        status = base_status
        # Cas "Sauvegarde XXX VPS" : nom dans l'objet, aucune erreur detectee
        # => le compte-rendu a bien ete genere, on considere le backup OK.
        if status is None and name in subject_l:
            status = 'ok'
        if status is None:
            continue

        existing = BackupCheck.query.filter_by(backup_id=b.id, check_date=today).first()
        if existing:
            existing.status = status
            existing.checked_by = source
            existing.comment = f'Mis a jour via {source}'
        else:
            db.session.add(BackupCheck(
                backup_id=b.id, check_date=today, status=status,
                checked_by=source, comment=f'Enregistre via {source}'))
        db.session.add(BackupHistory(
            backup_id=b.id, action='mail_ingest',
            comment=f'Statut {status} deduit du mail de backup', performed_by=source))
        results.append({'backup': b.service_name, 'status': status})

    if results:
        db.session.commit()
    return results


# --------------------------------------------------------------------------
# Connecteur "dossier" : lecture des mails de backup deposes dans un repertoire
# --------------------------------------------------------------------------

_EXT_OK = ('.eml', '.txt', '.html', '.htm', '.msg')


def _strip_html(html):
    text = re.sub(r'(?is)<(script|style).*?>.*?</\1>', ' ', html)
    text = re.sub(r'(?s)<br\s*/?>', '\n', text)
    text = re.sub(r'(?s)</(p|div|tr|li|h[1-6])>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    return text


def extract_email(path):
    """Retourne (subject, body_texte) depuis un fichier .eml/.txt/.html.
    Les .msg (Outlook) necessitent une lib externe -> non supportes ici."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.msg':
        raise ValueError("Format .msg non supporte (exporter en .eml ou .txt)")
    if ext == '.eml':
        with open(path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)
        subject = msg.get('subject', '') or ''
        part = msg.get_body(preferencelist=('plain', 'html'))
        if part is None:
            body = ''
        else:
            content = part.get_content()
            body = _strip_html(content) if part.get_content_subtype() == 'html' else content
        return subject, body
    # .txt / .html / .htm
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    if ext in ('.html', '.htm'):
        content = _strip_html(content)
    return os.path.basename(path), content


def scan_inbox(directory, source='mail-dossier'):
    """Traite chaque fichier-mail du repertoire, enregistre les checks et
    deplace le fichier dans le sous-dossier 'traites'. Retourne un resume."""
    if not directory or not os.path.isdir(directory):
        return {'error': f"Repertoire introuvable : {directory}", 'files': []}

    processed_dir = os.path.join(directory, 'traites')
    error_dir = os.path.join(directory, 'erreurs')
    files = []
    for path in sorted(glob.glob(os.path.join(directory, '*'))):
        if not os.path.isfile(path):
            continue
        if os.path.splitext(path)[1].lower() not in _EXT_OK:
            continue
        name = os.path.basename(path)
        try:
            subject, body = extract_email(path)
            results = parse_and_record(subject, body, source=source)
            files.append({'file': name, 'updated': results})
            os.makedirs(processed_dir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S_')
            shutil.move(path, os.path.join(processed_dir, stamp + name))
        except Exception as e:
            files.append({'file': name, 'error': str(e)})
            os.makedirs(error_dir, exist_ok=True)
            try:
                shutil.move(path, os.path.join(error_dir, name))
            except Exception:
                pass
    return {'files': files}
