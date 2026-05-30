from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import SystemUpdate, UpdateHistory
from app.decorators import require_edit, require_delete, view_guard

bp = Blueprint('updates', __name__)

STATUS_CHOICES = [
    ('up_to_date', 'À jour'),
    ('update_available', 'Mise à jour disponible'),
    ('critical', 'Critique / sécurité'),
]
TYPE_CHOICES = [('application', 'Application'), ('system', 'Système')]


@bp.before_request
def _guard_view():
    return view_guard('updates')


@bp.route('/')
@login_required
def list():
    updates = SystemUpdate.query.filter_by(is_active=True).order_by(SystemUpdate.name).all()
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    updates.sort(key=lambda u: rank.get(u.status_color(), 4))
    return render_template('updates/list.html', updates=updates,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        u = SystemUpdate(
            name=request.form.get('name', '').strip(),
            system_type=request.form.get('system_type', 'application'),
            current_version=request.form.get('current_version', '').strip() or None,
            latest_version=request.form.get('latest_version', '').strip() or None,
            status=request.form.get('status', 'up_to_date'),
            last_update=_parse_date(request.form.get('last_update')),
            updater_type=request.form.get('updater_type', 'interne'),
            updated_by=request.form.get('updated_by', '').strip() or None,
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(u)
        db.session.commit()
        db.session.add(UpdateHistory(update_id=u.id, action='creation',
                                     comment=f'Mise a jour creee : {u.name}', performed_by=current_user.username))
        db.session.commit()
        flash('Mise a jour ajoutee', 'success')
        return redirect(url_for('updates.list'))
    return render_template('updates/form.html', update=None,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)


@bp.route('/<int:id>')
@login_required
def detail(id):
    update = SystemUpdate.query.get_or_404(id)
    histories = update.histories.order_by(UpdateHistory.performed_at.desc()).all()
    return render_template('updates/detail.html', update=update, histories=histories,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    update = SystemUpdate.query.get_or_404(id)
    if request.method == 'POST':
        update.name = request.form.get('name', '').strip()
        update.system_type = request.form.get('system_type', 'application')
        update.current_version = request.form.get('current_version', '').strip() or None
        update.latest_version = request.form.get('latest_version', '').strip() or None
        update.status = request.form.get('status', 'up_to_date')
        update.last_update = _parse_date(request.form.get('last_update'))
        update.updater_type = request.form.get('updater_type', 'interne')
        update.updated_by = request.form.get('updated_by', '').strip() or None
        update.description = request.form.get('description')
        update.priority = request.form.get('priority', 'medium')
        db.session.commit()
        flash('Mise a jour modifiee', 'success')
        return redirect(url_for('updates.detail', id=id))
    return render_template('updates/form.html', update=update,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)


@bp.route('/<int:id>/mark-updated', methods=['POST'])
@login_required
@require_edit
def mark_updated(id):
    update = SystemUpdate.query.get_or_404(id)
    today = datetime.now(timezone.utc).date()
    if update.latest_version:
        update.current_version = update.latest_version
    update.status = 'up_to_date'
    update.last_update = today
    db.session.add(UpdateHistory(update_id=update.id, action='updated',
                                 comment=f'Mis a jour en version {update.current_version or "?"}',
                                 performed_by=current_user.username))
    db.session.commit()
    flash('Marque comme a jour', 'success')
    return redirect(url_for('updates.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    update = SystemUpdate.query.get_or_404(id)
    update.is_active = False
    db.session.add(UpdateHistory(update_id=update.id, action='deleted',
                                 comment=f'Mise a jour desactivee : {update.name}', performed_by=current_user.username))
    db.session.commit()
    flash('Entree supprimee', 'success')
    return redirect(url_for('updates.list'))


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return None
