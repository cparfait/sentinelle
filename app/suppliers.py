"""Annuaire des fournisseurs / prestataires (contacts support).

Rattache a la categorie de permission « contracts » (Contrats & fournisseurs).
"""
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required
from app import db
from app.models import Supplier, Equipment, Contract, SUPPLIER_KIND_LABELS
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('suppliers', __name__)


@bp.before_request
def _guard_view():
    return view_guard('contracts')


def _fill(supplier, form):
    supplier.name = form.get('name', '').strip()
    supplier.kind = form.get('kind', 'provider')
    supplier.contact_name = form.get('contact_name', '').strip() or None
    supplier.phone = form.get('phone', '').strip() or None
    supplier.support_phone = form.get('support_phone', '').strip() or None
    supplier.email = form.get('email', '').strip() or None
    supplier.support_url = form.get('support_url', '').strip() or None
    supplier.customer_ref = form.get('customer_ref', '').strip() or None
    supplier.hours = form.get('hours', '').strip() or None
    supplier.notes = form.get('notes') or None


@bp.route('/')
@login_required
def list():
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    suppliers = text_search(suppliers, q, ['name', 'contact_name', 'email',
                                           'customer_ref', 'notes'])
    suppliers, page, pages, total = paginate(suppliers)
    return render_template('suppliers/list.html', suppliers=suppliers, q=q,
                           page=page, pages=pages, total=total,
                           kind_labels=SUPPLIER_KIND_LABELS)


@bp.route('/<int:id>')
@login_required
def detail(id):
    supplier = Supplier.query.get_or_404(id)
    equipments = supplier.equipments.filter_by(is_active=True).order_by(Equipment.name).all()
    contracts = supplier.contracts.filter_by(is_active=True).order_by(
        Contract.end_date.asc().nullslast()).all()
    # Logiciels rattaches (Lot 2) : la relation peut ne pas exister encore.
    software = []
    if hasattr(supplier, 'software'):
        software = supplier.software.filter_by(is_active=True).all()
        software.sort(key=lambda s: (s.name or '').lower())
    return render_template('suppliers/detail.html', supplier=supplier,
                           equipments=equipments, contracts=contracts, software=software,
                           kind_labels=SUPPLIER_KIND_LABELS)


@bp.route('/quick-create', methods=['POST'])
@login_required
@require_edit
def quick_create():
    """Creation rapide (AJAX) d'un fournisseur minimal depuis un autre formulaire
    (ex. formulaire de contrat). Renvoie l'id + le nom en JSON."""
    name = (request.form.get('name', '') or '').strip()
    if not name:
        return jsonify(ok=False, error='Le nom est obligatoire.'), 400
    s = Supplier(
        name=name,
        contact_name=(request.form.get('contact_name', '') or '').strip() or None,
        phone=(request.form.get('phone', '') or '').strip() or None,
        email=(request.form.get('email', '') or '').strip() or None,
    )
    db.session.add(s)
    db.session.commit()
    audit_record('creation fournisseur', detail=f'{s.name} (ajout rapide)', category='contrats')
    return jsonify(ok=True, id=s.id, name=s.name)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        s = Supplier()
        _fill(s, request.form)
        if not s.name:
            flash('Le nom du fournisseur est obligatoire.', 'danger')
            return render_template('suppliers/form.html', supplier=None,
                                   kind_labels=SUPPLIER_KIND_LABELS)
        db.session.add(s)
        db.session.commit()
        audit_record('creation fournisseur', detail=s.name, category='contrats')
        flash('Fournisseur ajouté', 'success')
        return redirect(url_for('suppliers.list'))
    return render_template('suppliers/form.html', supplier=None,
                           kind_labels=SUPPLIER_KIND_LABELS)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    supplier = Supplier.query.get_or_404(id)
    if request.method == 'POST':
        _fill(supplier, request.form)
        db.session.commit()
        audit_record('modification fournisseur', detail=supplier.name, category='contrats')
        flash('Fournisseur modifié', 'success')
        return redirect(url_for('suppliers.list'))
    return render_template('suppliers/form.html', supplier=supplier,
                           kind_labels=SUPPLIER_KIND_LABELS)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    supplier = Supplier.query.get_or_404(id)
    supplier.is_active = False
    db.session.commit()
    audit_record('suppression fournisseur', detail=supplier.name, category='contrats')
    flash('Fournisseur supprimé', 'success')
    return redirect(url_for('suppliers.list'))
