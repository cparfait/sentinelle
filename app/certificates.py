from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (Certificate, CertificateHistory, Supplier, UserService,
                        CERT_KIND_LABELS, CIVILITY_LABELS, CERT_USAGE_LABELS,
                        CERT_SUPPORT_LABELS, CERT_VALIDITY_LABELS)
from app.cert_checker import fetch_cert_info
from app.inventory import active_equipments as _active_equipments
from app.inventory import parse_equipment_id as _parse_equipment_id
from app.forms_util import parse_date, parse_int, parse_float, status_rank

from app.decorators import require_edit, require_delete, view_guard
bp = Blueprint('certificates', __name__)


@bp.before_request
def _guard_view():
    return view_guard('certificates')


def _form_context():
    """Ce dont les DEUX formulaires ont besoin. Le certificat electronique
    puise ses autorites dans l'annuaire des societes : Certinomis et
    ChamberSign sont des fournisseurs comme les autres."""
    return {
        'equipments': _active_equipments(),
        'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all(),
        'services': UserService.options(),
        'kind_labels': CERT_KIND_LABELS,
        'civility_labels': CIVILITY_LABELS,
        'usage_labels': CERT_USAGE_LABELS,
        'support_labels': CERT_SUPPORT_LABELS,
        'validity_labels': CERT_VALIDITY_LABELS,
    }


def _fill_signature(cert, f):
    """Le volet propre au certificat electronique nominatif.

    Le code de revocation n'est ecrit QUE par qui a le droit de modifier la
    fiche -- ce que le decorateur de la route garantit deja. Un champ laisse
    vide n'efface pas le code enregistre : le formulaire ne le reaffiche pas en
    clair, et le renvoyer vide effacerait a chaque enregistrement un secret que
    personne n'a voulu retirer. Le mot-cle « - » le vide explicitement."""
    cert.supplier_id = parse_int(f.get('supplier_id'))
    cert.service_id = parse_int(f.get('service_id'))
    cert.civility = f.get('civility') if f.get('civility') in CIVILITY_LABELS else None
    cert.holder = (f.get('holder', '') or '').strip() or None
    cert.first_name = (f.get('first_name', '') or '').strip() or None
    cert.holder_role = (f.get('holder_role', '') or '').strip() or None
    cert.holder_email = (f.get('holder_email', '') or '').strip() or None
    cert.cert_usage = f.get('cert_usage') if f.get('cert_usage') in CERT_USAGE_LABELS else None
    cert.support = f.get('support') if f.get('support') in CERT_SUPPORT_LABELS else None
    cert.level = (f.get('level', '') or '').strip() or None
    cert.serial_number = (f.get('serial_number', '') or '').strip() or None
    cert.duration_years = parse_int(f.get('duration_years'), minimum=0)
    cert.amount_ttc = parse_float(f.get('amount_ttc'))
    cert.budget_code = (f.get('budget_code', '') or '').strip() or None
    cert.order_signed_on = parse_date(f.get('order_signed_on'))
    cert.validity = (f.get('validity') if f.get('validity') in CERT_VALIDITY_LABELS
                     else 'valide')
    code = (f.get('revocation_code', '') or '').strip()
    if code == '-':
        cert.revocation_code = None
    elif code:
        cert.revocation_code = code


def refresh_certificate_tls(cert, performed_by):
    """Met a jour la fiche depuis le certificat TLS lu en direct.
    Cree une entree d'historique mais NE COMMIT PAS (le caller s'en charge).
    Retourne (ok: bool, message: str)."""
    # Un certificat electronique n'a pas de domaine a interroger : sa date vient
    # de l'autorite, pas du reseau. Le dire plutot que de laisser une resolution
    # DNS echouer sur une chaine vide.
    if (cert.kind or 'tls') != 'tls' or not cert.domain:
        return False, "Lecture TLS impossible : ce certificat n'a pas de domaine."
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
    q = request.args.get('q', '').strip()
    # Onglets par nature. Les deux se surveillent pareil ; on les separe pour
    # les lire, pas pour les traiter differemment.
    kind = request.args.get('kind', '').strip()
    total_all = len(certificates)
    counts = {k: sum(1 for c in certificates if (c.kind or 'tls') == k)
              for k in CERT_KIND_LABELS}
    if kind in CERT_KIND_LABELS:
        certificates = [c for c in certificates if (c.kind or 'tls') == kind]
    from app.paging import paginate, text_search
    certificates = text_search(certificates, q, ['service_name', 'domain', 'issuer',
                                                 'holder', 'first_name', 'holder_role',
                                                 'serial_number', 'description'])
    certificates.sort(key=lambda c: status_rank(c.status()))
    certificates, page, pages, total = paginate(certificates)
    return render_template('certificates/list.html', certificates=certificates, q=q,
                           kind=kind, counts=counts, total_all=total_all,
                           kind_labels=CERT_KIND_LABELS,
                           page=page, pages=pages, total=total)


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


def _valide(kind, service_name, domain, expiry_date, holder):
    """Ce qu'il faut pour que la fiche veuille dire quelque chose, selon sa
    nature. Un certificat TLS sans domaine ne designe rien ; un certificat
    electronique sans titulaire ne dit pas qui signe. L'echeance est exigee des
    deux : c'est elle qu'on surveille, et c'est tout l'objet de la fiche."""
    if not service_name:
        return 'Le service est obligatoire.'
    if not expiry_date:
        return "La date d'expiration est obligatoire."
    if kind == 'signature':
        if not holder:
            return 'Le nom du titulaire est obligatoire.'
    elif not domain:
        return 'Le domaine est obligatoire.'
    return None


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    kind = request.values.get('kind')
    kind = kind if kind in CERT_KIND_LABELS else 'tls'
    if request.method == 'POST':
        service_name = (request.form.get('service_name') or '').strip()
        domain = (request.form.get('domain') or '').strip()
        expiry_date = parse_date(request.form.get('expiry_date'))
        erreur = _valide(kind, service_name, domain, expiry_date,
                         (request.form.get('holder') or '').strip())
        if erreur:
            flash(erreur, 'danger')
            return render_template('certificates/form.html', certificate=None,
                                   kind=kind, **_form_context())
        c = Certificate(
            kind=kind,
            service_name=service_name,
            domain=domain or None,
            issuer=request.form.get('issuer'),
            issued_at=parse_date(request.form.get('issued_at')),
            expiry_date=expiry_date,
            auto_renew=request.form.get('auto_renew') == 'on',
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
            equipment_id=_parse_equipment_id(request.form.get('equipment_id')),
        )
        if kind == 'signature':
            _fill_signature(c, request.form)
        db.session.add(c)
        db.session.commit()

        h = CertificateHistory(
            certificate_id=c.id, action='creation',
            comment=f'Certificat créé : {c.label()}', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Certificat ajouté avec succès', 'success')
        return redirect(url_for('certificates.list'))
    return render_template('certificates/form.html', certificate=None, kind=kind,
                           **_form_context())


@bp.route('/<int:id>')
@login_required
def detail(id):
    cert = Certificate.query.get_or_404(id)
    histories = cert.histories.order_by(CertificateHistory.performed_at.desc()).all()
    # Le code de revocation est un secret OPERATOIRE : il bloque les signatures
    # de son titulaire. La garde est ici, cote serveur -- ne pas l'afficher
    # suffirait a qui sait lire une page HTML.
    code = cert.revocation_code if current_user.can_edit('certificates') else None
    return render_template('certificates/detail.html', certificate=cert,
                           histories=histories, revocation_code=code)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    cert = Certificate.query.get_or_404(id)
    # La nature ne se change pas en cours de route : elle decide des champs que
    # la fiche porte, et basculer de l'une a l'autre laisserait derriere soi un
    # titulaire sur un certificat TLS, ou un domaine sur une carte a puce.
    kind = cert.kind or 'tls'
    if request.method == 'POST':
        service_name = (request.form.get('service_name') or '').strip()
        domain = (request.form.get('domain') or '').strip()
        expiry_date = parse_date(request.form.get('expiry_date'))
        erreur = _valide(kind, service_name, domain, expiry_date,
                         (request.form.get('holder') or '').strip())
        if erreur:
            flash(erreur, 'danger')
            return render_template('certificates/form.html', certificate=cert,
                                   kind=kind, **_form_context())
        cert.service_name = service_name
        cert.domain = domain or None
        cert.issuer = request.form.get('issuer')
        cert.issued_at = parse_date(request.form.get('issued_at'))
        cert.expiry_date = expiry_date
        cert.auto_renew = request.form.get('auto_renew') == 'on'
        cert.description = request.form.get('description')
        cert.priority = request.form.get('priority', 'medium')
        cert.equipment_id = _parse_equipment_id(request.form.get('equipment_id'))
        if kind == 'signature':
            _fill_signature(cert, request.form)
        db.session.commit()
        flash('Certificat modifié avec succès', 'success')
        return redirect(url_for('certificates.detail', id=id))
    return render_template('certificates/form.html', certificate=cert, kind=kind,
                           **_form_context())


@bp.route('/<int:id>/renew', methods=['POST'])
@login_required
@require_edit
def renew(id):
    cert = Certificate.query.get_or_404(id)
    new_expiry = parse_date(request.form.get('new_expiry_date'))
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
@require_delete
def delete(id):
    cert = Certificate.query.get_or_404(id)
    cert.is_active = False
    h = CertificateHistory(
        certificate_id=cert.id, action='deleted',
        comment=f'Certificat désactivé : {cert.service_name} - {cert.domain}', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Certificat supprimé', 'success')
    return redirect(url_for('certificates.list'))
