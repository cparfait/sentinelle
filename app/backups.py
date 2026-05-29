from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Backup, BackupCheck, BackupHistory
from sqlalchemy import func

from app.decorators import require_edit
bp = Blueprint('backups', __name__)


@bp.route('/')
@login_required
def list():
    backups = Backup.query.filter_by(is_active=True).all()
    today = datetime.now(timezone.utc).date()
    today_checks = {}
    for b in backups:
        today_checks[b.id] = b.today_check()
    return render_template('backups/list.html', backups=backups, today_checks=today_checks, today=today)


@bp.route('/daily', methods=['GET', 'POST'])
@login_required
@require_edit
def daily():
    backups = Backup.query.filter_by(is_active=True).order_by(Backup.service_name).all()
    today = datetime.now(timezone.utc).date()

    if request.method == 'POST':
        for b in backups:
            status = request.form.get(f'status_{b.id}')
            comment = request.form.get(f'comment_{b.id}', '')
            if status:
                existing = BackupCheck.query.filter_by(
                    backup_id=b.id, check_date=today
                ).first()
                if existing:
                    existing.status = status
                    existing.comment = comment
                    existing.checked_by = current_user.username
                else:
                    check = BackupCheck(
                        backup_id=b.id,
                        check_date=today,
                        status=status,
                        comment=comment if comment else None,
                        checked_by=current_user.username
                    )
                    db.session.add(check)
        db.session.commit()
        flash('Checks quotidiens enregistres', 'success')
        return redirect(url_for('backups.daily'))

    checks = {}
    for b in backups:
        checks[b.id] = BackupCheck.query.filter_by(
            backup_id=b.id, check_date=today
        ).first()

    return render_template('backups/daily.html', backups=backups, checks=checks, today=today)


@bp.route('/stats')
@login_required
def stats():
    backups = Backup.query.filter_by(is_active=True).all()
    today = datetime.now(timezone.utc).date()
    stats_data = []

    for b in backups:
        rate_30 = b.success_rate(30)
        rate_7 = b.success_rate(7)
        streak = b.streak()

        last_30 = []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            c = BackupCheck.query.filter_by(backup_id=b.id, check_date=d).first()
            last_30.append({
                'date': d.strftime('%Y-%m-%d'),
                'date_display': d.strftime('%d/%m'),
                'status': c.status if c else None,
                'comment': c.comment if c else None
            })

        total_ok = BackupCheck.query.filter_by(backup_id=b.id, status='ok').count()
        total_failed = BackupCheck.query.filter_by(backup_id=b.id, status='failed').count()
        total_warning = BackupCheck.query.filter_by(backup_id=b.id, status='warning').count()

        stats_data.append({
            'backup': b,
            'rate_30': rate_30,
            'rate_7': rate_7,
            'streak': streak,
            'total_ok': total_ok,
            'total_failed': total_failed,
            'total_warning': total_warning,
            'calendar': last_30
        })

    global_ok = sum(s['total_ok'] for s in stats_data)
    global_failed = sum(s['total_failed'] for s in stats_data)
    global_warning = sum(s['total_warning'] for s in stats_data)
    global_total = global_ok + global_failed + global_warning

    return render_template('backups/stats.html', stats_data=stats_data,
                           global_ok=global_ok, global_failed=global_failed,
                           global_warning=global_warning, global_total=global_total,
                           today=today)


@bp.route('/<int:id>')
@login_required
def detail(id):
    backup = Backup.query.get_or_404(id)
    checks = backup.checks.order_by(BackupCheck.check_date.desc()).limit(60).all()
    histories = BackupHistory.query.filter_by(backup_id=id).order_by(BackupHistory.performed_at.desc()).all()
    return render_template('backups/detail.html', backup=backup, checks=checks, histories=histories)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        b = Backup(
            service_name=request.form.get('service_name'),
            backup_type=request.form.get('backup_type'),
            location=request.form.get('location'),
            frequency=request.form.get('frequency'),
            expected_time=request.form.get('expected_time'),
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(b)
        db.session.commit()

        h = BackupHistory(
            backup_id=b.id, action='creation',
            comment='Backup cree', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Backup ajoute avec succes', 'success')
        return redirect(url_for('backups.list'))
    return render_template('backups/form.html', backup=None)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    backup = Backup.query.get_or_404(id)
    if request.method == 'POST':
        backup.service_name = request.form.get('service_name')
        backup.backup_type = request.form.get('backup_type')
        backup.location = request.form.get('location')
        backup.frequency = request.form.get('frequency')
        backup.expected_time = request.form.get('expected_time')
        backup.description = request.form.get('description')
        backup.priority = request.form.get('priority', 'medium')
        db.session.commit()
        flash('Backup modifie avec succes', 'success')
        return redirect(url_for('backups.detail', id=id))
    return render_template('backups/form.html', backup=backup)


@bp.route('/<int:id>/check', methods=['POST'])
@login_required
@require_edit
def check(id):
    backup = Backup.query.get_or_404(id)
    today = datetime.now(timezone.utc).date()
    status = request.form.get('status', 'ok')
    comment = request.form.get('comment', '')
    check_date_str = request.form.get('check_date')
    check_date = None
    if check_date_str:
        try:
            check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()
        except ValueError:
            check_date = today
    else:
        check_date = today

    existing = BackupCheck.query.filter_by(backup_id=id, check_date=check_date).first()
    if existing:
        existing.status = status
        existing.comment = comment if comment else existing.comment
        existing.checked_by = current_user.username
    else:
        c = BackupCheck(
            backup_id=id,
            check_date=check_date,
            status=status,
            comment=comment if comment else None,
            checked_by=current_user.username
        )
        db.session.add(c)
    db.session.commit()
    flash('Check enregistre', 'success')
    return redirect(url_for('backups.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_edit
def delete(id):
    backup = Backup.query.get_or_404(id)
    backup.is_active = False
    h = BackupHistory(
        backup_id=backup.id, action='deleted',
        comment='Backup desactive', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Backup supprime', 'success')
    return redirect(url_for('backups.list'))
