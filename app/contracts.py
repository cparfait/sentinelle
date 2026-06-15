"""Contrats, licences et abonnements : suivi des echeances et preavis.

La date qui declenche le statut/les alertes est `action_deadline()` =
echeance - preavis de resiliation (au-dela, tacite reconduction ou coupure).
"""
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import (Contract, ContractHistory, Supplier, Equipment,
                        CONTRACT_KIND_LABELS)
from app.decorators import require_edit, require_delete, view_guard

bp = Blueprint('contracts', __name__)


@bp.before_request
def _guard_view():
    return view_guard('contracts')


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return None


def _fill(c, f):
    c.name = (f.get('name', '') or '').strip()
    c.kind = f.get('kind') if f.get('kind') in CONTRACT_KIND_LABELS else 'maintenance'
    c.supplier_id = int(f['supplier_id']) if (f.get('supplier_id') or '').isdigit() else None
    c.reference = (f.get('reference', '') or '').strip() or None
    try:
        c.cost_yearly = float(f.get('cost_yearly').replace(',', '.')) if f.get('cost_yearly') else None
    except ValueError:
        c.cost_yearly = None
    c.start_date = _parse_date(f.get('start_date'))
    c.end_date = _parse_date(f.get('end_date'))
    try:
        c.notice_days = max(0, int(f.get('notice_days') or 0))
    except ValueError:
        c.notice_days = 0
    c.auto_renew = f.get('auto_renew') == 'on'
    c.equipment_id = int(f['equipment_id']) if (f.get('equipment_id') or '').isdigit() else None
    c.responsible = (f.get('responsible', '') or '').strip() or None
    c.description = f.get('description') or None
    c.priority = f.get('priority', 'medium')


def _form_context():
    return {
        'kind_labels': CONTRACT_KIND_LABELS,
        'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all(),
        'equipments': Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all(),
    }


@bp.route('/')
@login_required
def list():
    contracts = Contract.query.filter_by(is_active=True).order_by(
        Contract.end_date.asc().nullslast()).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    contracts = text_search(contracts, q, ['name', 'reference', 'description', 'responsible'])
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    contracts.sort(key=lambda c: rank.get(c.status(), 4))
    contracts, page, pages, total = paginate(contracts)
    total_cost = sum(c.cost_yearly or 0 for c in Contract.query.filter_by(is_active=True).all())
    return render_template('contracts/list.html', contracts=contracts, q=q,
                           page=page, pages=pages, total=total, total_cost=total_cost,
                           kind_labels=CONTRACT_KIND_LABELS)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        c = Contract()
        _fill(c, request.form)
        if not c.name:
            flash('Le nom du contrat est obligatoire.', 'danger')
            return render_template('contracts/form.html', contract=None, **_form_context())
        db.session.add(c)
        db.session.commit()
        db.session.add(ContractHistory(contract_id=c.id, action='creation',
                                       comment=f'Contrat cree : {c.name}',
                                       performed_by=current_user.username))
        db.session.commit()
        flash('Contrat ajouté', 'success')
        return redirect(url_for('contracts.list'))
    return render_template('contracts/form.html', contract=None, **_form_context())


@bp.route('/<int:id>')
@login_required
def detail(id):
    contract = Contract.query.get_or_404(id)
    histories = contract.histories.order_by(ContractHistory.performed_at.desc()).all()
    return render_template('contracts/detail.html', contract=contract, histories=histories)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    contract = Contract.query.get_or_404(id)
    if request.method == 'POST':
        old_end = contract.end_date
        _fill(contract, request.form)
        if old_end != contract.end_date:
            db.session.add(ContractHistory(
                contract_id=contract.id, action='echeance',
                comment='Échéance modifiée : '
                        f"{old_end.strftime('%d/%m/%Y') if old_end else '-'} -> "
                        f"{contract.end_date.strftime('%d/%m/%Y') if contract.end_date else '-'}",
                performed_by=current_user.username))
        db.session.commit()
        flash('Contrat modifié', 'success')
        return redirect(url_for('contracts.detail', id=id))
    return render_template('contracts/form.html', contract=contract, **_form_context())


@bp.route('/<int:id>/renew', methods=['POST'])
@login_required
@require_edit
def renew(id):
    """Marque le contrat comme renouvele : nouvelle echeance + trace."""
    contract = Contract.query.get_or_404(id)
    new_end = _parse_date(request.form.get('new_end_date'))
    if not new_end:
        flash('Indiquez la nouvelle date d\'échéance.', 'danger')
        return redirect(url_for('contracts.detail', id=id))
    old_end = contract.end_date
    contract.end_date = new_end
    comment = request.form.get('comment', '').strip()
    db.session.add(ContractHistory(
        contract_id=contract.id, action='renouvellement',
        comment=(f"Renouvelé jusqu'au {new_end.strftime('%d/%m/%Y')}"
                 + (f" (précédente échéance : {old_end.strftime('%d/%m/%Y')})" if old_end else '')
                 + (f' — {comment}' if comment else '')),
        performed_by=current_user.username))
    db.session.commit()
    flash(f"Contrat renouvelé jusqu'au {new_end.strftime('%d/%m/%Y')}", 'success')
    return redirect(url_for('contracts.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    contract = Contract.query.get_or_404(id)
    contract.is_active = False
    db.session.add(ContractHistory(contract_id=contract.id, action='deleted',
                                   comment=f'Contrat désactivé : {contract.name}',
                                   performed_by=current_user.username))
    db.session.commit()
    flash('Contrat supprimé', 'success')
    return redirect(url_for('contracts.list'))
