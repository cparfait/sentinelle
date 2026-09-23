from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import or_
from app import db
from app.models import (Account, Certificate, Backup, TestTask, Domain,
                        AccessReview, SystemUpdate, Equipment, Supplier, Contract,
                        ContractItem, Software, Consultation, Quote, Document, Referential)

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
                'detail': ('Certificat - expire ' + c.expiry_date.strftime('%d/%m/%Y')
                           if c.expiry_date else 'Certificat - echeance a completer'),
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
                Equipment.service_tag.ilike(like),
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


        software = Software.query.filter(
            Software.is_active,
            or_(
                Software.name.ilike(like),
                Software.version.ilike(like),
                Software.url.ilike(like),
                Software.responsible.ilike(like),
                Software.tech_responsible.ilike(like),
                Software.description.ilike(like),
                Software.supplier.has(Supplier.name.ilike(like)),
            )
        ).all()
        for s in software:
            editeur = f' - {s.supplier.name}' if s.supplier else ''
            results.append({
                'type': 'logiciel', 'icon': 'bi-window-stack',
                'label': f'{s.name}{" " + s.version if s.version else ""}',
                'detail': f'Logiciel - {s.hosting_label()}{editeur}',
                'url': f'/inventory/logiciels/{s.id}',
                'badge': s.computed_status(),
            })

        # Un devis se cherche par la societe qui l'a remis (fiche ou nom libre),
        # l'objet de la consultation ou ses notes ; il renvoie vers la fiche du
        # logiciel, ou vivent les consultations.
        quotes = Quote.query.join(Consultation).join(Software).filter(
            Software.is_active,
            or_(
                Quote.supplier_name.ilike(like),
                Quote.notes.ilike(like),
                Quote.supplier.has(Supplier.name.ilike(like)),
                Consultation.subject.ilike(like),
            )
        ).all()
        for qt in quotes:
            montant = (f' - {qt.amount:,.0f} €'.replace(',', ' ')
                       if qt.amount is not None else '')
            results.append({
                'type': 'devis', 'icon': 'bi-cash-coin',
                'label': f'{qt.who()}{montant}',
                'detail': f'Devis - {qt.consultation.software.name} - {qt.consultation.subject}',
                'url': f'/inventory/logiciels/{qt.consultation.software_id}#devis',
                'badge': 'success' if qt.selected else 'info',
            })

        # Une piece jointe se cherche par son nom de fichier ou sa categorie et
        # renvoie vers la fiche qui la porte : elle n'a pas d'ecran a elle.
        from app.documents import enabled as documents_enabled
        if documents_enabled():
            docs = Document.query.filter(
                or_(
                    Document.filename.ilike(like),
                    Document.category.has(Referential.label.ilike(like)),
                )
            ).all()
            for d in docs:
                target = _document_target(d)
                if target is None:
                    continue
                parent_label, url = target
                results.append({
                    'type': 'pièce jointe', 'icon': 'bi-paperclip',
                    'label': d.filename,
                    'detail': f'{d.category.label if d.category else "Pièce jointe"}'
                              f' - {parent_label} - {d.size_label()}',
                    'url': url,
                    'badge': 'info',
                    'perm': d.permission_category(),
                })

    # Visibilite : ne montrer que les categories autorisees pour l'utilisateur
    from flask_login import current_user
    _cat_perm = {'account': 'accounts', 'certificate': 'certificates',
                 'backup': 'backups', 'test': 'tests', 'domaine': 'domains',
                 'revue': 'reviews', 'mise à jour': 'updates', 'inventaire': 'inventory',
                 'fournisseur': 'contracts', 'contrat': 'contracts',
                 'logiciel': 'inventory', 'devis': 'contracts'}
    # Une piece jointe porte sa propre categorie (celle de sa fiche parente).
    results = [r for r in results
               if current_user.can_view(r.get('perm') or _cat_perm.get(r['type']))]

    return render_template('search.html', results=results, q=q)


def _document_target(doc):
    """La fiche qui porte une piece jointe : (libelle, url vers son onglet
    Documents). None si la piece est orpheline ou si sa fiche est a la
    corbeille -- on ne mene pas a une page qui repondrait 404 ni a un parent
    qui n'existe plus."""
    if doc.software_id:
        sw = db.session.get(Software, doc.software_id)
        if sw and sw.is_active:
            return f'Logiciel {sw.name}', f'/inventory/logiciels/{sw.id}#documents'
    elif doc.contract_id:
        ct = db.session.get(Contract, doc.contract_id)
        if ct and ct.is_active:
            return f'Contrat {ct.name}', f'/contracts/{ct.id}#documents'
    elif doc.contract_item_id:
        item = db.session.get(ContractItem, doc.contract_item_id)
        if item and item.contract and item.contract.is_active:
            return f'Contrat {item.contract.name}', f'/contracts/{item.contract_id}#documents'
    elif doc.quote_id:
        qt = db.session.get(Quote, doc.quote_id)
        if qt and qt.consultation.software.is_active:
            sw = qt.consultation.software
            return f'Devis {qt.who()} ({sw.name})', f'/inventory/logiciels/{sw.id}#devis'
    elif doc.supplier_id:
        sup = db.session.get(Supplier, doc.supplier_id)
        if sup and sup.is_active:
            return f'Fournisseur {sup.name}', f'/suppliers/{sup.id}#documents'
    elif doc.certificate_id:
        c = db.session.get(Certificate, doc.certificate_id)
        if c and c.is_active:
            return f'Certificat {c.service_name}', f'/certificates/{c.id}#documents'
    elif doc.equipment_id:
        e = db.session.get(Equipment, doc.equipment_id)
        if e and e.is_active:
            return f'Matériel {e.name}', f'/inventory/{e.id}'
    return None
