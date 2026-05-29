from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Certificate, CertificateHistory

from app.decorators import require_edit
bp = Blueprint('certificates', __name__)


@bp.route('/')
@login_required
def list():
    certificates = Certificate.query.filter_by(is_active=True).order_by(Certificate.expiry_date.asc()).all()
    return render_template('certificates/list.html', certificates=certificates)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        c = Certificate(
            service_name=request.form.get('service_name'),
            domain=request.form.get('domain'),
            issuer=request.form.get('issuer'),
            issued_at=_parse_date(request.form.get('issued_at')),
            expiry_date=_parse_date(request.form.get('expiry_date')),
            auto_renew=request.form.get('auto_renew') == 'on',
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(c)
        db.session.commit()

        h = CertificateHistory(
            certificate_id=c.id, action='creation',
            comment='Certificat créé', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Certificat ajouté avec succès', 'success')
        return redirect(url_for('certificates.list'))
    return render_template('certificates/form.html', certificate=None)


@bp.route('/<int:id>')
@login_required
def detail(id):
    cert = Certificate.query.get_or_404(id)
    histories = cert.histories.order_by(CertificateHistory.performed_at.desc()).all()
    return render_template('certificates/detail.html', certificate=cert, histories=histories)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    cert = Certificate.query.get_or_404(id)
    if request.method == 'POST':
        cert.service_name = request.form.get('service_name')
        cert.domain = request.form.get('domain')
        cert.issuer = request.form.get('issuer')
        cert.issued_at = _parse_date(request.form.get('issued_at'))
        cert.expiry_date = _parse_date(request.form.get('expiry_date'))
        cert.auto_renew = request.form.get('auto_renew') == 'on'
        cert.description = request.form.get('description')
        cert.priority = request.form.get('priority', 'medium')
        db.session.commit()
        flash('Certificat modifié avec succès', 'success')
        return redirect(url_for('certificates.detail', id=id))
    return render_template('certificates/form.html', certificate=cert)


@bp.route('/<int:id>/renew', methods=['POST'])
@login_required
@require_edit
def renew(id):
    cert = Certificate.query.get_or_404(id)
    new_expiry = _parse_date(request.form.get('new_expiry_date'))
    comment = request.form.get('comment', 'Certificat renouvelé')
    if new_expiry:
        cert.expiry_date = new_expiry
        cert.issued_at = datetime.now(timezone.utc).date()
    h = CertificateHistory(
        certificate_id=cert.id, action='renewed',
        comment=comment, performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Certificat marqué comme renouvelé', 'success')
    return redirect(url_for('certificates.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_edit
def delete(id):
    cert = Certificate.query.get_or_404(id)
    cert.is_active = False
    h = CertificateHistory(
        certificate_id=cert.id, action='deleted',
        comment='Certificat désactivé', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Certificat supprimé', 'success')
    return redirect(url_for('certificates.list'))


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return None
