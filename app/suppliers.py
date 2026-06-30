"""Annuaire des fournisseurs / prestataires (contacts support).

Rattache a la categorie de permission « contracts » (Contrats & fournisseurs).
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required
from app import db
from app.models import Supplier, SUPPLIER_KIND_LABELS
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
