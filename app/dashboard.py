from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import Account, Certificate, Backup, BackupCheck, TestTask, AlertLog, Domain
from app.snooze import is_snoozed
from app import db

from app.decorators import require_edit
bp = Blueprint('dashboard', __name__)


@bp.route('/')
@login_required
def index():
    today = datetime.now(timezone.utc).date()

    accounts = Account.query.filter_by(is_active=True).all()
    certificates = Certificate.query.filter_by(is_active=True).all()
    domains = Domain.query.filter_by(is_active=True).all()
    backups = Backup.query.filter_by(is_active=True).all()
    tests = TestTask.query.filter_by(is_active=True).all()

    acc_danger = sum(1 for a in accounts if a.status() == 'danger')
    acc_warning = sum(1 for a in accounts if a.status() == 'warning')
    acc_ok = sum(1 for a in accounts if a.status() == 'success')

    cert_danger = sum(1 for c in certificates if c.status() == 'danger')
    cert_warning = sum(1 for c in certificates if c.status() == 'warning')
    cert_ok = sum(1 for c in certificates if c.status() == 'success')

    dom_danger = sum(1 for d in domains if d.status() == 'danger')
    dom_warning = sum(1 for d in domains if d.status() == 'warning')
    dom_ok = sum(1 for d in domains if d.status() == 'success')

    bkp_danger = sum(1 for b in backups if b.computed_status() == 'danger')
    bkp_warning = sum(1 for b in backups if b.computed_status() == 'warning')
    bkp_ok = sum(1 for b in backups if b.computed_status() == 'success')

    tst_danger = sum(1 for t in tests if t.computed_status() == 'danger')
    tst_warning = sum(1 for t in tests if t.computed_status() == 'warning')
    tst_ok = sum(1 for t in tests if t.computed_status() == 'success')

    urgent_items = []
    for a in accounts:
        if a.status() == 'danger':
            days = (a.next_password_change - today).days if a.next_password_change else 'N/A'
            urgent_items.append({
                'type': 'account', 'name': f'{a.service_name} ({a.username})',
                'detail': f'MDP a changer depuis {abs(days)} jour(s)' if isinstance(days, int) and days < 0 else f'MDP a changer dans {days} jour(s)',
                'status': 'danger', 'url': f'/accounts/{a.id}'
            })
    for c in certificates:
        if c.status() in ('danger', 'warning'):
            days = (c.expiry_date - today).days
            urgent_items.append({
                'type': 'certificate', 'name': f'{c.service_name} - {c.domain}',
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': c.status(), 'url': f'/certificates/{c.id}'
            })
    for d in domains:
        if d.status() in ('danger', 'warning') and d.expiry_date:
            days = (d.expiry_date - today).days
            urgent_items.append({
                'type': 'domain', 'name': d.name,
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': d.status(), 'url': f'/domains/{d.id}'
            })
    for b in backups:
        if b.computed_status() == 'danger':
            tc = b.today_check()
            detail = 'Non verifie' if not tc else f'Check: {tc.status}'
            urgent_items.append({
                'type': 'backup', 'name': b.service_name,
                'detail': detail,
                'status': 'danger', 'url': f'/backups/{b.id}'
            })
    for t in tests:
        if t.computed_status() == 'danger':
            days = (t.next_due - today).days if t.next_due else 'N/A'
            urgent_items.append({
                'type': 'test', 'name': t.name,
                'detail': f'Test en retard de {abs(days)} jour(s)' if isinstance(days, int) and days < 0 else f'Test a faire dans {days} jour(s)',
                'status': 'danger', 'url': f'/tests/{t.id}'
            })

    urgent_items.sort(key=lambda x: {'danger': 0, 'warning': 1, 'info': 2}.get(x['status'], 3))

    recent_alerts = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(10).all()

    backup_checks = {}
    for b in backups:
        backup_checks[b.id] = BackupCheck.query.filter_by(
            backup_id=b.id, check_date=today
        ).first()

    stats = {
        'accounts': {'total': len(accounts), 'danger': acc_danger, 'warning': acc_warning, 'ok': acc_ok},
        'certificates': {'total': len(certificates), 'danger': cert_danger, 'warning': cert_warning, 'ok': cert_ok},
        'domains': {'total': len(domains), 'danger': dom_danger, 'warning': dom_warning, 'ok': dom_ok},
        'backups': {'total': len(backups), 'danger': bkp_danger, 'warning': bkp_warning, 'ok': bkp_ok},
        'tests': {'total': len(tests), 'danger': tst_danger, 'warning': tst_warning, 'ok': tst_ok},
    }

    return render_template('dashboard.html', stats=stats, urgent_items=urgent_items,
                           recent_alerts=recent_alerts, backups=backups,
                           backup_checks=backup_checks, today=today)


@bp.route('/quick-check', methods=['POST'])
@login_required
def quick_check():
    if not current_user.can_edit('backups'):
        flash("Vous n'avez pas les droits pour valider un backup.", 'danger')
        return redirect(url_for('dashboard.index'))
    backup_id = request.form.get('backup_id')
    status = request.form.get('status', 'ok')
    comment = request.form.get('comment', '')
    today = datetime.now(timezone.utc).date()

    existing = BackupCheck.query.filter_by(backup_id=backup_id, check_date=today).first()
    if existing:
        existing.status = status
        existing.comment = comment if comment else existing.comment
        existing.checked_by = current_user.username
    else:
        check = BackupCheck(
            backup_id=backup_id,
            check_date=today,
            status=status,
            comment=comment if comment else None,
            checked_by=current_user.username
        )
        db.session.add(check)
    db.session.commit()
    flash('Backup valide', 'success')
    return redirect(url_for('dashboard.index'))
