from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import SystemUpdate, UpdateHistory, Asset
from app.forms_util import parse_date, status_rank
from app.decorators import require_edit, require_delete, view_guard
from app.inventory import active_equipments as _active_equipments
from app.inventory import parse_equipment_id as _parse_equipment_id

bp = Blueprint('updates', __name__)

STATUS_CHOICES = [
    ('up_to_date', 'À jour'),
    ('update_available', 'Mise à jour disponible'),
    ('critical', 'Critique / sécurité'),
]
TYPE_CHOICES = [('application', 'Application'), ('system', 'Système')]
_VALID_STATUS = {v for v, _ in STATUS_CHOICES}
_VALID_TYPE = {v for v, _ in TYPE_CHOICES}


def _clean_status(value):
    return value if value in _VALID_STATUS else 'up_to_date'


def _clean_type(value):
    return value if value in _VALID_TYPE else 'application'


@bp.before_request
def _guard_view():
    return view_guard('updates')


@bp.route('/')
@login_required
def list():
    updates = SystemUpdate.query.filter_by(is_active=True).order_by(SystemUpdate.name).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    updates = text_search(updates, q, ['name', 'current_version', 'latest_version',
                                       'updated_by', 'description'])
    updates.sort(key=lambda u: status_rank(u.status_color()))
    updates, page, pages, total = paginate(updates)
    return render_template('updates/list.html', updates=updates,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES,
                           q=q, page=page, pages=pages, total=total)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom est obligatoire.', 'danger')
            return render_template('updates/form.html', update=None, assets=_active_assets(),
                                   equipments=_active_equipments(),
                                   status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)
        u = SystemUpdate(
            name=name,
            system_type=_clean_type(request.form.get('system_type')),
            current_version=request.form.get('current_version', '').strip() or None,
            latest_version=request.form.get('latest_version', '').strip() or None,
            status=_clean_status(request.form.get('status')),
            last_update=parse_date(request.form.get('last_update')),
            updater_type=request.form.get('updater_type', 'interne'),
            updated_by=request.form.get('updated_by', '').strip() or None,
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
            equipment_id=_parse_equipment_id(request.form.get('equipment_id')),
        )
        db.session.add(u)
        db.session.commit()
        db.session.add(UpdateHistory(update_id=u.id, action='creation',
                                     comment=f'Mise a jour creee : {u.name}', performed_by=current_user.username))
        db.session.commit()
        flash('Mise a jour ajoutee', 'success')
        return redirect(url_for('updates.list'))
    return render_template('updates/form.html', update=None, assets=_active_assets(),
                           equipments=_active_equipments(),
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
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom est obligatoire.', 'danger')
            return render_template('updates/form.html', update=update, assets=_active_assets(),
                                   equipments=_active_equipments(),
                                   status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES)
        update.name = name
        update.system_type = _clean_type(request.form.get('system_type'))
        update.current_version = request.form.get('current_version', '').strip() or None
        update.latest_version = request.form.get('latest_version', '').strip() or None
        update.status = _clean_status(request.form.get('status'))
        update.last_update = parse_date(request.form.get('last_update'))
        update.updater_type = request.form.get('updater_type', 'interne')
        update.updated_by = request.form.get('updated_by', '').strip() or None
        update.description = request.form.get('description')
        update.priority = request.form.get('priority', 'medium')
        update.equipment_id = _parse_equipment_id(request.form.get('equipment_id'))
        db.session.commit()
        flash('Mise a jour modifiee', 'success')
        return redirect(url_for('updates.detail', id=id))
    return render_template('updates/form.html', update=update, assets=_active_assets(),
                           equipments=_active_equipments(),
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
    note = (request.form.get('comment', '') or '').strip()
    comment = f'Mis a jour en version {update.current_version or "?"}'
    if note:
        comment += f' — {note}'
    db.session.add(UpdateHistory(update_id=update.id, action='updated',
                                 comment=comment, performed_by=current_user.username))
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


def _active_assets():
    return Asset.query.filter_by(is_active=True).order_by(Asset.name).all()
