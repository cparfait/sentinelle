"""API JSON interne — endpoints légers pour le polling navigateur."""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from flask_login import login_required, current_user

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.route('/alert-count')
@login_required
def alert_count():
    """Retourne le nombre d'entités en statut critique (danger) par catégorie.
    Utilisé par le polling JS pour les toasts de notification."""
    from app.models import (Account, Certificate, Domain, Backup, TestTask,
                            AccessReview, SystemUpdate, Equipment, Contract,
                            AlertSnooze)
    today = datetime.now(timezone.utc).date()
    snoozed = {}
    for s in AlertSnooze.query.filter(AlertSnooze.snoozed_until >= today).all():
        snoozed.setdefault(s.entity_type, set()).add(s.entity_id)

    def _cnt(items, statusf, etype):
        skip = snoozed.get(etype, ())
        return sum(1 for i in items if i.id not in skip and statusf(i) == 'danger')

    cats = {}
    if current_user.can_view('accounts'):
        cats['accounts'] = _cnt(Account.query.filter_by(is_active=True).all(), lambda o: o.status(), 'account')
    if current_user.can_view('certificates'):
        cats['certificates'] = _cnt(Certificate.query.filter_by(is_active=True).all(), lambda o: o.status(), 'certificate')
    if current_user.can_view('domains'):
        cats['domains'] = _cnt(Domain.query.filter_by(is_active=True).all(), lambda o: o.status(), 'domain')
    if current_user.can_view('backups'):
        cats['backups'] = _cnt(Backup.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'backup')
    if current_user.can_view('tests'):
        cats['tests'] = _cnt(TestTask.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'test')
    if current_user.can_view('reviews'):
        cats['reviews'] = _cnt(AccessReview.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'review')
    if current_user.can_view('updates'):
        cats['updates'] = _cnt(SystemUpdate.query.filter_by(is_active=True).all(), lambda o: o.status_color(), 'update')
    if current_user.can_view('inventory'):
        cats['inventory'] = _cnt(Equipment.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'equipment')
    if current_user.can_view('contracts'):
        cats['contracts'] = _cnt(Contract.query.filter_by(is_active=True).all(), lambda o: o.status(), 'contract')

    return jsonify(danger=sum(cats.values()), by_category=cats)
