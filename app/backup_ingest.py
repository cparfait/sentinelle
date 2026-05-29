"""Analyse d'un mail recap de backup et enregistrement automatique des checks.

Heuristique v1, volontairement tolerante : pour chaque sauvegarde active, on
cherche les lignes du mail qui mentionnent son nom de service, puis on en deduit
le statut a partir de mots-cles. A affiner avec un vrai exemple de recap.
"""
from datetime import datetime, timezone

from app import db
from app.models import Backup, BackupCheck, BackupHistory

FAIL_KW = ['fail', 'echec', 'échec', 'erreur', 'error', 'aborted', 'interrompu',
           'unsuccessful', 'ko']
WARN_KW = ['warning', 'avertissement', 'attention', 'mitige', 'mitigé', 'partial',
           'partiel']
SUCCESS_KW = ['success', 'succes', 'succès', 'reussi', 'réussi', 'completed',
              'complete', 'terminé', 'termine', 'ok']


def _status_from_line(line):
    t = line.lower()
    if any(k in t for k in FAIL_KW):
        return 'failed'
    if any(k in t for k in WARN_KW):
        return 'warning'
    if any(k in t for k in SUCCESS_KW):
        return 'ok'
    return None


def _rank(status):
    return {'failed': 3, 'warning': 2, 'ok': 1}.get(status, 0)


def parse_and_record(subject, body, source='mail-recap'):
    """Met a jour le check du jour des backups mentionnes dans le mail.
    Retourne la liste [{'backup':.., 'status':..}] des backups mis a jour."""
    today = datetime.now(timezone.utc).date()
    lines = f"{subject or ''}\n{body or ''}".splitlines()

    results = []
    for b in Backup.query.filter_by(is_active=True).all():
        name = (b.service_name or '').strip().lower()
        if not name:
            continue
        best = None
        for line in lines:
            if name in line.lower():
                s = _status_from_line(line)
                if s and _rank(s) > _rank(best):
                    best = s
        if not best:
            continue

        existing = BackupCheck.query.filter_by(backup_id=b.id, check_date=today).first()
        if existing:
            existing.status = best
            existing.checked_by = source
            existing.comment = f'Mis a jour via {source}'
        else:
            db.session.add(BackupCheck(
                backup_id=b.id, check_date=today, status=best,
                checked_by=source, comment=f'Enregistre via {source}'))
        db.session.add(BackupHistory(
            backup_id=b.id, action='mail_ingest',
            comment=f'Statut {best} deduit du mail recap', performed_by=source))
        results.append({'backup': b.service_name, 'status': best})

    if results:
        db.session.commit()
    return results
