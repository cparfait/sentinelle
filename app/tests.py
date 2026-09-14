from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import TestTask, TestHistory
from app.forms_util import parse_date, parse_int, status_rank

from app.decorators import require_edit, require_delete, view_guard
bp = Blueprint('tests', __name__)


@bp.before_request
def _guard_view():
    return view_guard('tests')

TEST_TYPES = [
    ('restoration', 'Test de restauration'),
    ('sensitive_backup', 'Sauvegarde données sensibles sur clé'),
    ('disaster_recovery', 'Test PCA/PRA'),
    ('integrity_check', 'Vérification d\'intégrité'),
    ('other', 'Autre'),
]


@bp.route('/')
@login_required
def list():
    tests = TestTask.query.filter_by(is_active=True).order_by(TestTask.next_due.asc().nullsfirst()).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    tests = text_search(tests, q, ['name', 'test_type', 'description'])
    tests.sort(key=lambda t: status_rank(t.computed_status()))
    tests, page, pages, total = paginate(tests)
    return render_template('tests/list.html', tests=tests, test_types=TEST_TYPES, q=q, page=page, pages=pages, total=total)


@bp.route('/kanban')
@login_required
def kanban():
    tests = TestTask.query.filter_by(is_active=True).all()
    cols = {
        'pending': {'label': 'À faire', 'icon': 'bi-clock', 'color': 'secondary', 'items': []},
        'success': {'label': 'Réussi', 'icon': 'bi-check-circle', 'color': 'success', 'items': []},
        'failed': {'label': 'En échec', 'icon': 'bi-x-circle', 'color': 'danger', 'items': []},
    }
    for t in tests:
        status = t.status or 'pending'
        key = status if status in cols else 'pending'
        cols[key]['items'].append(t)
    # Trier chaque colonne : plus urgent en premier
    for col in cols.values():
        col['items'].sort(key=lambda t: (
            (t.next_due - datetime.now(timezone.utc).date()).days
            if t.next_due else 9999
        ))
    return render_template('tests/kanban.html', cols=cols)


_VALID_STATUS = {'pending', 'success', 'failed'}

@bp.route('/<int:id>/set-status', methods=['POST'])
@login_required
@require_edit
def set_status(id):
    test = TestTask.query.get_or_404(id)
    status = request.form.get('status', 'pending')
    if status not in _VALID_STATUS:
        status = 'pending'
    test.status = status
    db.session.add(TestHistory(test_id=test.id, action='status_change',
                               comment=f'Statut changé en {status} (Kanban)',
                               performed_by=current_user.username))
    db.session.commit()
    flash(f'Statut mis à jour : {status}', 'success')
    return redirect(request.referrer or url_for('tests.kanban'))


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Le nom du test est obligatoire.', 'danger')
            return render_template('tests/form.html', test=None, test_types=TEST_TYPES)
        last_performed = parse_date(request.form.get('last_performed'))
        freq = parse_int(request.form.get('frequency_days'), 90, minimum=1)
        next_due = parse_date(request.form.get('next_due'))
        if not next_due and last_performed:
            next_due = last_performed + timedelta(days=freq)
        t = TestTask(
            name=name,
            test_type=request.form.get('test_type'),
            description=request.form.get('description'),
            last_performed=last_performed,
            next_due=next_due,
            frequency_days=freq,
            status='pending',
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(t)
        db.session.commit()

        h = TestHistory(
            test_id=t.id, action='creation',
            comment=f'Test créé : {t.name}', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Test ajouté avec succès', 'success')
        return redirect(url_for('tests.list'))
    return render_template('tests/form.html', test=None, test_types=TEST_TYPES)


@bp.route('/<int:id>')
@login_required
def detail(id):
    test = TestTask.query.get_or_404(id)
    histories = test.histories.order_by(TestHistory.performed_at.desc()).all()
    return render_template('tests/detail.html', test=test, histories=histories, test_types=TEST_TYPES)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    test = TestTask.query.get_or_404(id)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Le nom du test est obligatoire.', 'danger')
            return render_template('tests/form.html', test=test, test_types=TEST_TYPES)
        test.name = name
        test.test_type = request.form.get('test_type')
        test.description = request.form.get('description')
        test.last_performed = parse_date(request.form.get('last_performed'))
        test.frequency_days = parse_int(request.form.get('frequency_days'), 90, minimum=1)
        test.next_due = parse_date(request.form.get('next_due'))
        test.priority = request.form.get('priority', 'medium')
        db.session.commit()
        flash('Test modifié avec succès', 'success')
        return redirect(url_for('tests.detail', id=id))
    return render_template('tests/form.html', test=test, test_types=TEST_TYPES)


@bp.route('/<int:id>/complete', methods=['POST'])
@login_required
@require_edit
def complete(id):
    test = TestTask.query.get_or_404(id)
    result = request.form.get('result', '')
    comment = request.form.get('comment', '')
    outcome = request.form.get('outcome', 'success')
    today = datetime.now(timezone.utc).date()
    test.last_performed = today
    test.next_due = today + timedelta(days=test.frequency_days)
    test.status = outcome
    test.result = result
    h = TestHistory(
        test_id=test.id, action='completed',
        result=result, comment=comment, performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Test marqué comme effectué', 'success')
    return redirect(url_for('tests.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    test = TestTask.query.get_or_404(id)
    test.is_active = False
    h = TestHistory(
        test_id=test.id, action='deleted',
        comment=f'Test désactivé : {test.name}', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Test supprimé', 'success')
    return redirect(url_for('tests.list'))
