from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import AccessReview, ReviewHistory
from app.decorators import require_edit, require_delete, view_guard

bp = Blueprint('reviews', __name__)


@bp.before_request
def _guard_view():
    return view_guard('reviews')


@bp.route('/')
@login_required
def list():
    reviews = AccessReview.query.filter_by(is_active=True).order_by(
        AccessReview.next_review.asc().nullsfirst()).all()
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    reviews.sort(key=lambda r: rank.get(r.computed_status(), 4))
    return render_template('reviews/list.html', reviews=reviews)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        last_review = _parse_date(request.form.get('last_review'))
        freq = int(request.form.get('frequency_days', 365) or 365)
        next_review = _parse_date(request.form.get('next_review'))
        if not next_review and last_review:
            next_review = last_review + timedelta(days=freq)
        r = AccessReview(
            application=request.form.get('application', '').strip(),
            responsible=request.form.get('responsible', '').strip() or None,
            scope=request.form.get('scope'),
            frequency_days=freq,
            last_review=last_review,
            next_review=next_review,
            status='pending',
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(r)
        db.session.commit()
        db.session.add(ReviewHistory(review_id=r.id, action='creation',
                                     comment='Revue creee', performed_by=current_user.username))
        db.session.commit()
        flash('Revue de droits ajoutee', 'success')
        return redirect(url_for('reviews.list'))
    return render_template('reviews/form.html', review=None)


@bp.route('/<int:id>')
@login_required
def detail(id):
    review = AccessReview.query.get_or_404(id)
    histories = review.histories.order_by(ReviewHistory.performed_at.desc()).all()
    return render_template('reviews/detail.html', review=review, histories=histories)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    review = AccessReview.query.get_or_404(id)
    if request.method == 'POST':
        review.application = request.form.get('application', '').strip()
        review.responsible = request.form.get('responsible', '').strip() or None
        review.scope = request.form.get('scope')
        review.frequency_days = int(request.form.get('frequency_days', 365) or 365)
        review.last_review = _parse_date(request.form.get('last_review'))
        review.next_review = _parse_date(request.form.get('next_review'))
        review.priority = request.form.get('priority', 'medium')
        db.session.commit()
        flash('Revue modifiee', 'success')
        return redirect(url_for('reviews.detail', id=id))
    return render_template('reviews/form.html', review=review)


@bp.route('/<int:id>/complete', methods=['POST'])
@login_required
@require_edit
def complete(id):
    review = AccessReview.query.get_or_404(id)
    outcome = request.form.get('outcome', 'completed')
    comment = request.form.get('comment', '')
    today = datetime.now(timezone.utc).date()
    review.last_review = today
    review.next_review = today + timedelta(days=review.frequency_days or 365)
    review.status = outcome
    db.session.add(ReviewHistory(review_id=review.id, action='completed',
                                 comment=comment or 'Revue effectuee',
                                 performed_by=current_user.username))
    db.session.commit()
    flash('Revue marquee comme effectuee', 'success')
    return redirect(url_for('reviews.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    review = AccessReview.query.get_or_404(id)
    review.is_active = False
    db.session.add(ReviewHistory(review_id=review.id, action='deleted',
                                 comment='Revue desactivee', performed_by=current_user.username))
    db.session.commit()
    flash('Revue supprimee', 'success')
    return redirect(url_for('reviews.list'))


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return None
