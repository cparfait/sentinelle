from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import or_
from app.models import (Account, Certificate, Backup, TestTask, Domain,
                        AccessReview, SystemUpdate, Equipment, Supplier, Contract)

bp = Blueprint('search', __name__)


@bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    results = []
    if q and len(q) >= 2:
        like = f'%{q}%'

        accounts = Account.query.filter(
            Account.is_active,
            or_(
                Account.service_name.ilike(like),
                Account.username.ilike(like),
                Account.url.ilike(like),
                Account.description.ilike(like),
            )
        ).all()
        for a in accounts:
            results.append({
                'type': 'account', 'icon': 'bi-key',
                'label': f'{a.service_name} ({a.username})',
                'detail': 'Compte MDP',
                'url': f'/accounts/{a.id}',
                'badge': 'info'
            })

        certs = Certificate.query.filter(
            Certificate.is_active,
            or_(
                Certificate.service_name.ilike(like),
                Certificate.domain.ilike(like),
                Certificate.issuer.ilike(like),
                Certificate.description.ilike(like),
            )
        ).all()
        for c in certs:
            results.append({
                'type': 'certificate', 'icon': 'bi-award',
                'label': f'{c.service_name} - {c.domain}',
                'detail': f'Certificat - expire {c.expiry_date.strftime("%d/%m/%Y")}',
                'url': f'/certificates/{c.id}',
                'badge': 'success'
            })

        backups = Backup.query.filter(
            Backup.is_active,
            or_(
                Backup.service_name.ilike(like),
                Backup.location.ilike(like),
                Backup.description.ilike(like),
            )
        ).all()
        for b in backups:
            results.append({
                'type': 'backup', 'icon': 'bi-cloud-arrow-up',
                'label': b.service_name,
                'detail': f'Backup - {b.backup_type or ""}',
                'url': f'/backups/{b.id}',
                'badge': 'warning'
            })

        tests = TestTask.query.filter(
            TestTask.is_active,
            or_(
                TestTask.name.ilike(like),
                TestTask.description.ilike(like),
                TestTask.test_type.ilike(like),
            )
        ).all()
        for t in tests:
            results.append({
                'type': 'test', 'icon': 'bi-clipboard-check',
                'label': t.name,
                'detail': f'Test - {t.test_type}',
                'url': f'/tests/{t.id}',
                'badge': 'info'
            })

        domains = Domain.query.filter(
            Domain.is_active,
            or_(
                Domain.name.ilike(like),
                Domain.registrar.ilike(like),
                Domain.description.ilike(like),
            )
        ).all()
        for d in domains:
            results.append({
                'type': 'domaine', 'icon': 'bi-globe',
                'label': d.name,
                'detail': f'Domaine - {d.registrar or ""}',
                'url': f'/domains/{d.id}',
                'badge': 'info'
            })

        reviews = AccessReview.query.filter(
            AccessReview.is_active,
            or_(
                AccessReview.application.ilike(like),
                AccessReview.responsible.ilike(like),
                AccessReview.scope.ilike(like),
            )
        ).all()
        for r in reviews:
            results.append({
                'type': 'revue', 'icon': 'bi-person-check',
                'label': r.application,
                'detail': f'Revue de droits{" - " + r.responsible if r.responsible else ""}',
                'url': f'/reviews/{r.id}',
                'badge': 'warning'
            })

        updates = SystemUpdate.query.filter(
            SystemUpdate.is_active,
            or_(
                SystemUpdate.name.ilike(like),
                SystemUpdate.current_version.ilike(like),
                SystemUpdate.latest_version.ilike(like),
                SystemUpdate.updated_by.ilike(like),
                SystemUpdate.description.ilike(like),
            )
        ).all()
        for u in updates:
            results.append({
                'type': 'mise à jour', 'icon': 'bi-arrow-up-circle',
                'label': u.name,
                'detail': f'MàJ - {u.current_version or "?"}',
                'url': f'/updates/{u.id}',
                'badge': u.status_color(),
            })

        equipments = Equipment.query.filter(
            Equipment.is_active,
            or_(
                Equipment.name.ilike(like),
                Equipment.ip_address.ilike(like),
                Equipment.os.ilike(like),
                Equipment.role_principal.ilike(like),
                Equipment.serial_number.ilike(like),
                Equipment.host_server.ilike(like),
            )
        ).all()
        for e in equipments:
            results.append({
                'type': 'inventaire', 'icon': 'bi-hdd-stack',
                'label': e.name,
                'detail': f'{e.kind_label()}{" - " + e.ip_address if e.ip_address else ""}',
                'url': f'/inventory/{e.id}',
                'badge': e.computed_status(),
            })

        from urllib.parse import quote
        suppliers = Supplier.query.filter(
            Supplier.is_active,
            or_(
                Supplier.name.ilike(like),
                Supplier.contact_name.ilike(like),
                Supplier.email.ilike(like),
                Supplier.customer_ref.ilike(like),
            )
        ).all()
        for s in suppliers:
            results.append({
                'type': 'fournisseur', 'icon': 'bi-building',
                'label': s.name,
                'detail': f'Fournisseur - {s.kind_label()}',
                'url': f'/suppliers/?q={quote(s.name)}',
                'badge': 'info',
            })

        contracts = Contract.query.filter(
            Contract.is_active,
            or_(
                Contract.name.ilike(like),
                Contract.reference.ilike(like),
                Contract.description.ilike(like),
            )
        ).all()
        for c in contracts:
            results.append({
                'type': 'contrat', 'icon': 'bi-file-earmark-text',
                'label': c.name,
                'detail': f'Contrat - {c.kind_label()}',
                'url': f'/contracts/{c.id}',
                'badge': c.status(),
            })

    # Visibilite : ne montrer que les categories autorisees pour l'utilisateur
    from flask_login import current_user
    _cat_perm = {'account': 'accounts', 'certificate': 'certificates',
                 'backup': 'backups', 'test': 'tests', 'domaine': 'domains',
                 'revue': 'reviews', 'mise à jour': 'updates', 'inventaire': 'inventory',
                 'fournisseur': 'contracts', 'contrat': 'contracts'}
    results = [r for r in results
               if current_user.can_view(_cat_perm.get(r['type']))]

    return render_template('search.html', results=results, q=q)
