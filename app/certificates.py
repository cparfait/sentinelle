from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Certificate, CertificateHistory
from app.cert_checker import fetch_cert_info

from app.decorators import require_edit
bp = Blueprint('certificates', __name__)


def refresh_certificate_tls(cert, performed_by):
    """Met a jour la fiche depuis le certificat TLS lu en direct.
    Cree une entree d'historique mais NE COMMIT PAS (le caller s'en charge).
    Retourne (ok: bool, message: str)."""
    try:
        info = fetch_cert_info(cert.domain)
    except Exception as e:
        db.session.add(CertificateHistory(
            certificate_id=cert.id, action='tls_check_failed',
            comment=f"Echec lecture TLS : {e}", performed_by=performed_by))
        return False, f"Verification TLS impossible : {e}"

    old = cert.expiry_date
    cert.expiry_date = info['expiry_date']
    if info['issuer']:
        cert.issuer = info['issuer']
    msg = f"Expiration mise a jour via TLS : {info['expiry_date'].strftime('%d/%m/%Y')}"
    if old and old != info['expiry_date']:
        msg += f" (avant : {old.strftime('%d/%m/%Y')})"
    db.session.add(CertificateHistory(
        certificate_id=cert.id, action='tls_check',
        comment=msg, performed_by=performed_by))
    return True, msg


@bp.route('/')
@login_required
def list():
    certificates = Certificate.query.filter_by(is_active=True).order_by(Certificate.expiry_date.asc()).all()
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    certificates.sort(key=lambda c: rank.get(c.status(), 4))
    return render_template('certificates/list.html', certificates=certificates)


@bp.route('/check-domain')
@login_required
@require_edit
def check_domain():
    """Lit en direct le certificat d'un domaine (pour pre-remplir le formulaire).
    Renvoie du JSON ; utilise par le bouton "Verifier" de la fiche."""
    domain = request.args.get('domain', '').strip()
    if not domain:
        return jsonify(ok=False, error="Renseignez d'abord le domaine."), 400
    try:
        info = fetch_cert_info(domain)
        return jsonify(ok=True, expiry_date=info['expiry_date'].isoformat(),
                       issuer=info['issuer'] or '')
    except Exception as e:
        return jsonify(ok=False, error=str(e))


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


@bp.route('/<int:id>/check-tls', methods=['POST'])
@login_required
@require_edit
def check_tls(id):
    cert = Certificate.query.get_or_404(id)
    ok, message = refresh_certificate_tls(cert, current_user.username)
    db.session.commit()
    flash(message, 'success' if ok else 'danger')
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
