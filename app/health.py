from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app import db

bp = Blueprint('health', __name__)


@bp.route('/health')
def health():
    """Endpoint de surveillance : vérifie que l'app et la base répondent.
    Retourne HTTP 200/JSON quand tout va bien, 503 sinon."""
    try:
        db.session.execute(db.text('SELECT 1'))
        from app.models import (Account, Certificate, Backup, TestTask,
                                AccessReview, Domain, SystemUpdate)
        counts = {
            'accounts': Account.query.filter_by(is_active=True).count(),
            'certificates': Certificate.query.filter_by(is_active=True).count(),
            'backups': Backup.query.filter_by(is_active=True).count(),
            'tests': TestTask.query.filter_by(is_active=True).count(),
            'reviews': AccessReview.query.filter_by(is_active=True).count(),
            'domains': Domain.query.filter_by(is_active=True).count(),
            'updates': SystemUpdate.query.filter_by(is_active=True).count(),
        }
        return jsonify(
            status='ok',
            ts=datetime.now(timezone.utc).isoformat(),
            counts=counts
        ), 200
    except Exception as e:
        return jsonify(status='error', error=str(e)), 503
