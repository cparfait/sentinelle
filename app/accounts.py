from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Account, AccountHistory

from app.decorators import require_edit
bp = Blueprint('accounts', __name__)


@bp.route('/')
@login_required
def list():
    accounts = Account.query.filter_by(is_active=True).order_by(Account.next_password_change.asc()).all()
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    accounts.sort(key=lambda a: rank.get(a.status(), 4))
    return render_template('accounts/list.html', accounts=accounts)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        a = Account(
            service_name=request.form.get('service_name'),
            username=request.form.get('username'),
            url=request.form.get('url'),
            description=request.form.get('description'),
            last_password_change=_parse_date(request.form.get('last_password_change')),
            rotation_days=int(request.form.get('rotation_days', 90)),
            priority=request.form.get('priority', 'medium'),
        )
        if a.last_password_change:
            a.next_password_change = a.last_password_change + timedelta(days=a.rotation_days)
        db.session.add(a)
        db.session.commit()

        h = AccountHistory(
            account_id=a.id, action='creation',
            comment='Compte créé', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Compte ajouté avec succès', 'success')
        return redirect(url_for('accounts.list'))
    return render_template('accounts/form.html', account=None)


@bp.route('/<int:id>')
@login_required
def detail(id):
    account = Account.query.get_or_404(id)
    histories = account.histories.order_by(AccountHistory.performed_at.desc()).all()
    return render_template('accounts/detail.html', account=account, histories=histories)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    account = Account.query.get_or_404(id)
    if request.method == 'POST':
        account.service_name = request.form.get('service_name')
        account.username = request.form.get('username')
        account.url = request.form.get('url')
        account.description = request.form.get('description')
        account.last_password_change = _parse_date(request.form.get('last_password_change'))
        account.rotation_days = int(request.form.get('rotation_days', 90))
        account.priority = request.form.get('priority', 'medium')
        if account.last_password_change:
            account.next_password_change = account.last_password_change + timedelta(days=account.rotation_days)
        db.session.commit()
        flash('Compte modifié avec succès', 'success')
        return redirect(url_for('accounts.detail', id=id))
    return render_template('accounts/form.html', account=account)


@bp.route('/<int:id>/password-changed', methods=['POST'])
@login_required
@require_edit
def password_changed(id):
    account = Account.query.get_or_404(id)
    today = datetime.now(timezone.utc).date()
    account.last_password_change = today
    account.next_password_change = today + timedelta(days=account.rotation_days)
    comment = request.form.get('comment', 'Mot de passe changé')
    h = AccountHistory(
        account_id=account.id, action='password_changed',
        comment=comment, performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Mot de passe marqué comme changé', 'success')
    return redirect(url_for('accounts.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_edit
def delete(id):
    account = Account.query.get_or_404(id)
    account.is_active = False
    h = AccountHistory(
        account_id=account.id, action='deleted',
        comment='Compte désactivé', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Compte supprimé', 'success')
    return redirect(url_for('accounts.list'))


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return None
