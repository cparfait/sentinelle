"""Gestion des reports d'alerte (snooze / acquittement)."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import AlertSnooze

VALID_TYPES = ('account', 'certificate', 'backup', 'test', 'domain', 'review',
               'update', 'equipment', 'contract')


def get_active_snooze(entity_type, entity_id):
    """Retourne le snooze actif (snoozed_until >= aujourd'hui) ou None."""
    today = datetime.now(timezone.utc).date()
    return AlertSnooze.query.filter(
        AlertSnooze.entity_type == entity_type,
        AlertSnooze.entity_id == int(entity_id),
        AlertSnooze.snoozed_until >= today,
    ).first()


def is_snoozed(entity_type, entity_id):
    return get_active_snooze(entity_type, entity_id) is not None


def active_snooze_keys():
    """Ensemble des (entity_type, entity_id) ayant un report actif aujourd'hui,
    charge en UNE requete. A privilegier dans les boucles (digest, badges) au
    lieu d'appeler is_snoozed() par element (N+1)."""
    today = datetime.now(timezone.utc).date()
    rows = AlertSnooze.query.filter(AlertSnooze.snoozed_until >= today).all()
    return {(r.entity_type, r.entity_id) for r in rows}


def set_snooze(entity_type, entity_id, days, reason=None, created_by=None):
    """Cree ou met a jour le report pour `days` jours (a partir d'aujourd'hui)."""
    until = datetime.now(timezone.utc).date() + timedelta(days=int(days))
    existing = AlertSnooze.query.filter_by(
        entity_type=entity_type, entity_id=int(entity_id)).first()
    if existing:
        existing.snoozed_until = until
        existing.reason = reason
        existing.created_by = created_by
        existing.created_at = datetime.now(timezone.utc)
    else:
        db.session.add(AlertSnooze(
            entity_type=entity_type, entity_id=int(entity_id),
            snoozed_until=until, reason=reason, created_by=created_by))
    db.session.commit()
    return until


def clear_snooze(entity_type, entity_id):
    AlertSnooze.query.filter_by(
        entity_type=entity_type, entity_id=int(entity_id)).delete()
    db.session.commit()
