from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required, current_user
from app import db
from app.models import Domain, DomainHistory, CtLogEntry
from app.domain_checker import fetch_domain_info
from app.ct_monitor import scan_domain
from app.forms_util import parse_date, parse_int, status_rank
from app.decorators import require_edit, require_delete, view_guard

bp = Blueprint('domains', __name__)


@bp.before_request
def _guard_view():
    return view_guard('domains')


def refresh_domain_rdap(domain, performed_by):
    """Met a jour la fiche depuis le RDAP. Cree un historique, NE COMMIT PAS.
    Retourne (ok, message)."""
    try:
        info = fetch_domain_info(domain.name)
    except Exception as e:
        db.session.add(DomainHistory(
            domain_id=domain.id, action='rdap_check_failed',
            comment=f"Echec RDAP : {e}", performed_by=performed_by))
        return False, f"Verification RDAP impossible : {e}"

    if not info.get('expiry_date'):
        db.session.add(DomainHistory(
            domain_id=domain.id, action='rdap_check',
            comment="RDAP n'a pas fourni de date d'expiration", performed_by=performed_by))
        return False, "Le RDAP n'a pas fourni de date d'expiration pour ce domaine."

    old = domain.expiry_date
    domain.expiry_date = info['expiry_date']
    if info.get('registrar'):
        domain.registrar = info['registrar']
        if domain.registrar_id is None:
            fiche = _fournisseur_par_nom(domain.registrar)
            domain.registrar_id = fiche.id if fiche else None
    msg = f"Expiration mise a jour via RDAP : {info['expiry_date'].strftime('%d/%m/%Y')}"
    if old and old != info['expiry_date']:
        msg += f" (avant : {old.strftime('%d/%m/%Y')})"
    db.session.add(DomainHistory(
        domain_id=domain.id, action='rdap_check', comment=msg, performed_by=performed_by))
    return True, msg


@bp.route('/')
@login_required
def list():
    domains = Domain.query.filter_by(is_active=True).order_by(
        Domain.expiry_date.asc().nullslast()).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    domains = text_search(domains, q, ['name', 'registrar', 'description'])
    domains.sort(key=lambda d: status_rank(d.status()))
    domains, page, pages, total = paginate(domains)
    return render_template('domains/list.html', domains=domains, q=q, page=page, pages=pages, total=total)


@bp.route('/check-rdap-domain')
@login_required
@require_edit
def check_rdap_domain():
    """Lecture RDAP a la volee pour pre-remplir le formulaire (JSON)."""
    name = request.args.get('domain', '').strip()
    if not name:
        return jsonify(ok=False, error="Renseignez d'abord le domaine."), 400
    try:
        info = fetch_domain_info(name)
        return jsonify(ok=True,
                       expiry_date=info['expiry_date'].isoformat() if info['expiry_date'] else '',
                       registrar=info.get('registrar') or '')
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom de domaine est obligatoire.', 'danger')
            return render_template('domains/form.html', domain=None, **_form_context())
        registrar, registrar_id = _registrar_depuis(request.form)
        d = Domain(
            name=name,
            registrar=registrar,
            registrar_id=registrar_id,
            expiry_date=parse_date(request.form.get('expiry_date')),
            auto_renew=request.form.get('auto_renew') == 'on',
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
        )
        db.session.add(d)
        db.session.commit()
        db.session.add(DomainHistory(domain_id=d.id, action='creation',
                                     comment=f'Domaine cree : {d.name}', performed_by=current_user.username))
        n = d.rattacher_certificats()
        db.session.commit()
        flash('Domaine ajoute avec succes' + (f' ({n} certificat(s) rattaché(s))' if n else ''), 'success')
        return redirect(url_for('domains.list'))
    return render_template('domains/form.html', domain=None, **_form_context())


@bp.route('/<int:id>')
@login_required
def detail(id):
    domain = Domain.query.get_or_404(id)
    histories = domain.histories.order_by(DomainHistory.performed_at.desc()).all()
    # Certificats vus dans les journaux CT : les nouveaux d'abord, puis les plus recents.
    ct_entries = domain.ct_entries.order_by(
        CtLogEntry.crtsh_id.desc()).limit(50).all()
    ct_entries.sort(key=lambda e: (e.status != 'new', -(e.crtsh_id or 0)))
    ct_new = domain.ct_new_count()
    certificats = sorted(domain.certificates.filter_by(is_active=True).all(),
                         key=lambda c: (c.expiry_date is None, c.expiry_date))
    return render_template('domains/detail.html', domain=domain, histories=histories,
                           certificats=certificats,
                           ct_entries=ct_entries, ct_new=ct_new)


@bp.route('/<int:id>/scan-ct', methods=['POST'])
@login_required
@require_edit
def scan_ct(id):
    """Scan manuel des journaux de Certificate Transparency (crt.sh)."""
    domain = Domain.query.get_or_404(id)
    res = scan_domain(domain, current_user.username)
    if res['error']:
        flash(f"Scan CT impossible : {res['error']}", 'danger')
    elif res['baseline']:
        flash(f"Ligne de base CT etablie : {res['baseline']} certificat(s) "
              "enregistre(s) (pas d'alerte sur l'historique).", 'info')
    elif res['new']:
        flash(f"{len(res['new'])} nouveau(x) certificat(s) detecte(s) dans les "
              "journaux CT — a verifier.", 'warning')
    else:
        flash("Aucun nouveau certificat dans les journaux CT.", 'success')
    return redirect(url_for('domains.detail', id=id))


@bp.route('/<int:id>/ct-ack', methods=['POST'])
@login_required
@require_edit
def ct_ack(id):
    """Marque tous les certificats CT 'new' comme verifies."""
    domain = Domain.query.get_or_404(id)
    now = datetime.now(timezone.utc)
    n = 0
    for e in domain.ct_entries.filter_by(status='new').all():
        e.status = 'acknowledged'
        e.acknowledged_by = current_user.username
        e.acknowledged_at = now
        n += 1
    if n:
        db.session.add(DomainHistory(
            domain_id=domain.id, action='ct_acknowledged',
            comment=f"{n} certificat(s) CT marque(s) comme verifie(s).",
            performed_by=current_user.username))
    db.session.commit()
    flash(f"{n} certificat(s) marque(s) comme verifie(s).", 'success')
    return redirect(url_for('domains.detail', id=id))


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    domain = Domain.query.get_or_404(id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom de domaine est obligatoire.', 'danger')
            return render_template('domains/form.html', domain=domain, **_form_context())
        domain.name = name
        domain.registrar, domain.registrar_id = _registrar_depuis(request.form)
        domain.expiry_date = parse_date(request.form.get('expiry_date'))
        domain.auto_renew = request.form.get('auto_renew') == 'on'
        domain.description = request.form.get('description')
        domain.priority = request.form.get('priority', 'medium')
        domain.rattacher_certificats()
        db.session.commit()
        flash('Domaine modifie avec succes', 'success')
        return redirect(url_for('domains.detail', id=id))
    return render_template('domains/form.html', domain=domain, **_form_context())


def _form_context():
    from app.models import Supplier
    return {'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()}


def _fournisseur_par_nom(nom):
    """La fiche fournisseur que designe ce nom, ou None. Rapprochement exact
    (casse ignoree) : « OVH » ne designe pas « OVHcloud », c'est a l'humain de
    le dire. Deux homonymes actifs : aucun."""
    from sqlalchemy import func
    from app.models import Supplier
    if not nom:
        return None
    candidats = Supplier.query.filter(Supplier.is_active.is_(True),
                                      func.lower(Supplier.name) == nom.strip().lower()).all()
    return candidats[0] if len(candidats) == 1 else None


def _registrar_depuis(form):
    """(texte, registrar_id) depuis le formulaire. La fiche choisie prime ;
    sans choix, le texte cherche sa fiche par nom. Une fiche choisie sans
    texte prete son nom au texte, pour la liste et les mails."""
    from app.models import Supplier
    texte = (form.get('registrar', '') or '').strip() or None
    choisi = parse_int(form.get('registrar_id'))
    fiche = Supplier.query.get(choisi) if choisi else None
    if fiche is None or not fiche.is_active:
        fiche = _fournisseur_par_nom(texte)
    if fiche is not None and not texte:
        texte = fiche.name
    return texte, (fiche.id if fiche else None)


@bp.route('/<int:id>/check-rdap', methods=['POST'])
@login_required
@require_edit
def check_rdap(id):
    domain = Domain.query.get_or_404(id)
    ok, message = refresh_domain_rdap(domain, current_user.username)
    db.session.commit()
    flash(message, 'success' if ok else 'danger')
    return redirect(url_for('domains.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    domain = Domain.query.get_or_404(id)
    domain.is_active = False
    db.session.add(DomainHistory(domain_id=domain.id, action='deleted',
                                 comment=f'Domaine desactive : {domain.name}', performed_by=current_user.username))
    db.session.commit()
    flash('Domaine supprime', 'success')
    return redirect(url_for('domains.list'))
