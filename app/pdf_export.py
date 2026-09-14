"""Routes d'export PDF par entité."""
from flask import Blueprint, send_file, abort
from flask_login import login_required, current_user
import io

bp = Blueprint('pdf_export', __name__)


def _pdf_response(pdf_bytes, filename):
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


@bp.route('/accounts/<int:id>/pdf')
@login_required
def account_pdf(id):
    if not current_user.can_view('accounts'):
        abort(403)
    from app.models import Account, AccountHistory
    account = Account.query.get_or_404(id)
    histories = AccountHistory.query.filter_by(account_id=id).order_by(AccountHistory.performed_at.desc()).limit(20).all()
    from app.pdf_entity import _build
    rows = [
        ('Service', account.service_name),
        ('Utilisateur', account.username),
        ('URL', account.url or '—'),
        ('Dernier changement', account.last_password_change.strftime('%d/%m/%Y') if account.last_password_change else '—'),
        ('Prochain changement', account.next_password_change.strftime('%d/%m/%Y') if account.next_password_change else '—'),
        ('Priorité', account.priority or '—'),
        ('Description', account.description or '—'),
    ]
    pdf = _build(account.service_name, account.username, rows, account.status(), histories)
    return _pdf_response(pdf, f'compte-{account.id}.pdf')


@bp.route('/certificates/<int:id>/pdf')
@login_required
def certificate_pdf(id):
    if not current_user.can_view('certificates'):
        abort(403)
    from app.models import Certificate, CertificateHistory
    cert = Certificate.query.get_or_404(id)
    histories = CertificateHistory.query.filter_by(certificate_id=id).order_by(CertificateHistory.performed_at.desc()).limit(20).all()
    from app.pdf_entity import _build
    rows = [
        ('Service', cert.service_name),
        ('Domaine', cert.domain),
        ('Émetteur', cert.issuer or '—'),
        ('Expiration', cert.expiry_date.strftime('%d/%m/%Y') if cert.expiry_date else '—'),
        ('Auto-renouvellement', 'Oui' if cert.auto_renew else 'Non'),
        ('Priorité', cert.priority or '—'),
        ('Description', cert.description or '—'),
    ]
    pdf = _build(cert.service_name, cert.domain, rows, cert.status(), histories)
    return _pdf_response(pdf, f'certificat-{cert.id}.pdf')


@bp.route('/domains/<int:id>/pdf')
@login_required
def domain_pdf(id):
    if not current_user.can_view('domains'):
        abort(403)
    from app.models import Domain, DomainHistory
    domain = Domain.query.get_or_404(id)
    histories = DomainHistory.query.filter_by(domain_id=id).order_by(DomainHistory.performed_at.desc()).limit(20).all()
    from app.pdf_entity import _build
    rows = [
        ('Domaine', domain.name),
        ('Registrar', domain.registrar or '—'),
        ('Expiration', domain.expiry_date.strftime('%d/%m/%Y') if domain.expiry_date else '—'),
        ('Renouvellement auto', 'Oui' if domain.auto_renew else 'Non'),
        ('Priorité', domain.priority or '—'),
        ('Description', domain.description or '—'),
    ]
    pdf = _build(domain.name, domain.registrar or '', rows, domain.status(), histories)
    return _pdf_response(pdf, f'domaine-{domain.id}.pdf')


@bp.route('/tests/<int:id>/pdf')
@login_required
def test_pdf(id):
    if not current_user.can_view('tests'):
        abort(403)
    from app.models import TestTask, TestHistory
    test = TestTask.query.get_or_404(id)
    histories = TestHistory.query.filter_by(test_id=id).order_by(TestHistory.performed_at.desc()).limit(20).all()
    from app.pdf_entity import _build
    rows = [
        ('Nom', test.name),
        ('Type', test.test_type or '—'),
        ('Dernier test', test.last_performed.strftime('%d/%m/%Y') if test.last_performed else '—'),
        ('Prochain test', test.next_due.strftime('%d/%m/%Y') if test.next_due else '—'),
        ('Fréquence', f'{test.frequency_days} jour(s)' if test.frequency_days else '—'),
        ('Statut', test.status or '—'),
        ('Priorité', test.priority or '—'),
        ('Description', test.description or '—'),
    ]
    pdf = _build(test.name, test.test_type or '', rows, test.computed_status(), histories)
    return _pdf_response(pdf, f'test-{test.id}.pdf')
