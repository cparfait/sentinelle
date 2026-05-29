from datetime import datetime, timezone
from flask import (Blueprint, render_template, current_app, request, redirect,
                   url_for, flash)
from flask_login import login_required, current_user
from app import db
from app.models import AlertLog
from app.email_service import send_email, render_alert_email
from app.snooze import set_snooze, clear_snooze, VALID_TYPES
from app.decorators import require_edit

bp = Blueprint('alerts', __name__)

# Ou rediriger apres un snooze, selon le type d'element
_DETAIL_ENDPOINT = {
    'account': 'accounts.detail',
    'certificate': 'certificates.detail',
    'backup': 'backups.detail',
    'test': 'tests.detail',
    'domain': 'domains.detail',
}


@bp.route('/')
@login_required
def list():
    alerts = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(100).all()
    return render_template('alerts/list.html', alerts=alerts)


@bp.route('/snooze', methods=['POST'])
@login_required
@require_edit
def snooze():
    entity_type = request.form.get('entity_type', '')
    entity_id = request.form.get('entity_id', '')
    days = request.form.get('days', '7')
    reason = request.form.get('reason', '').strip() or None
    if entity_type not in VALID_TYPES or not entity_id.isdigit() or not days.isdigit():
        flash('Report impossible : parametres invalides.', 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))
    until = set_snooze(entity_type, entity_id, int(days), reason, current_user.username)
    flash(f"Alerte reportee jusqu'au {until.strftime('%d/%m/%Y')}.", 'success')
    return redirect(url_for(_DETAIL_ENDPOINT[entity_type], id=int(entity_id)))


@bp.route('/unsnooze', methods=['POST'])
@login_required
@require_edit
def unsnooze():
    entity_type = request.form.get('entity_type', '')
    entity_id = request.form.get('entity_id', '')
    if entity_type not in VALID_TYPES or not entity_id.isdigit():
        flash('Operation impossible.', 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))
    clear_snooze(entity_type, entity_id)
    flash('Report annule, les alertes reprennent.', 'success')
    return redirect(url_for(_DETAIL_ENDPOINT[entity_type], id=int(entity_id)))


def send_alert(subject, body, entity_type=None, entity_id=None, entity_name=None,
               status='danger'):
    recipients = current_app.config.get('ALERT_RECIPIENTS', [])
    recipients = [r.strip() for r in recipients if r.strip()]
    if not recipients:
        return

    try:
        url = None
        if entity_type and entity_id:
            base = current_app.config.get('APP_BASE_URL', '').rstrip('/')
            if base:
                url = f"{base}/{entity_type}s/{entity_id}"
        html_body = render_alert_email(subject, body, status=status, url=url)
        send_email(subject, recipients, body, html_body=html_body)

        log = AlertLog(
            alert_type='email',
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            message=body,
            recipients=', '.join(recipients),
            status='sent'
        )
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as e:
        log = AlertLog(
            alert_type='email',
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            message=f"ERREUR: {str(e)}\n{body}",
            recipients=', '.join(recipients),
            status='failed'
        )
        db.session.add(log)
        db.session.commit()
        return False
