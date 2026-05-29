from datetime import datetime, timezone
from flask import Blueprint, render_template, current_app
from flask_login import login_required
from app import db
from app.models import AlertLog
from app.email_service import send_email, render_alert_email

bp = Blueprint('alerts', __name__)


@bp.route('/')
@login_required
def list():
    alerts = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(100).all()
    return render_template('alerts/list.html', alerts=alerts)


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
