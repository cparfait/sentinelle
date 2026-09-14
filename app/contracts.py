"""Contrats, licences et abonnements : suivi des echeances et preavis.

La date qui declenche le statut/les alertes est `action_deadline()` =
echeance - preavis de resiliation (au-dela, tacite reconduction ou coupure).
"""
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required, current_user
from app import db
from app.models import (Contract, ContractHistory, ContractItem, Consultation,
                        Quote, Supplier, Equipment, Software,
                        CONTRACT_KIND_LABELS, CONTRACT_NATURE_LABELS,
                        CONTRACT_ITEM_KIND_LABELS)
from app.forms_util import parse_date, parse_int, parse_float, status_rank
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('contracts', __name__)


@bp.before_request
def _guard_view():
    return view_guard('contracts')


def _fill(c, f):
    c.name = (f.get('name', '') or '').strip()
    c.kind = f.get('kind') if f.get('kind') in CONTRACT_KIND_LABELS else 'maintenance'
    c.nature = f.get('nature') if f.get('nature') in CONTRACT_NATURE_LABELS else None
    c.supplier_id = parse_int(f.get('supplier_id'))
    c.reference = (f.get('reference', '') or '').strip() or None
    c.supplier_reference = (f.get('supplier_reference', '') or '').strip() or None
    c.cost_yearly = parse_float(f.get('cost_yearly'))
    c.cost_max_yearly = parse_float(f.get('cost_max_yearly'))
    c.cost_total = parse_float(f.get('cost_total'))
    c.start_date = parse_date(f.get('start_date'))
    c.end_date = parse_date(f.get('end_date'))
    c.firm_years = parse_int(f.get('firm_years'), minimum=0)
    # Zero est une reponse -- « non reconductible » ; l'absence n'en est pas
    # une. parse_int rend None sur une saisie vide, ce qui les distingue.
    c.renewals = parse_int(f.get('renewals'), minimum=0)
    c.renewal_years = parse_int(f.get('renewal_years'), minimum=0)
    c.notice_days = parse_int(f.get('notice_days'), 0, minimum=0)
    c.auto_renew = f.get('auto_renew') == 'on'
    # Equipements couverts (multi-selection) : on ne garde que des equipements actifs.
    ids = [parse_int(v) for v in f.getlist('equipment_ids')]
    ids = [i for i in ids if i]
    c.equipments = (Equipment.query.filter(Equipment.id.in_(ids),
                                           Equipment.is_active.is_(True)).all()
                    if ids else [])
    # Logiciels couverts (multi-selection). Un marche couvre AUTANT de logiciels
    # qu'il en couvre reellement -- UGAP, marches communs a deux applications :
    # c'est ici que se pose le rattachement.
    sids = [parse_int(v) for v in f.getlist('software_ids')]
    sids = [i for i in sids if i]
    c.software = (Software.query.filter(Software.id.in_(sids),
                                        Software.is_active.is_(True)).all()
                  if sids else [])
    c.responsible = (f.get('responsible', '') or '').strip() or None
    c.description = f.get('description') or None
    c.priority = f.get('priority', 'medium')


def _form_context():
    return {
        'kind_labels': CONTRACT_KIND_LABELS,
        'nature_labels': CONTRACT_NATURE_LABELS,
        'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all(),
        'equipments': Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all(),
        'software_list': Software.query.filter_by(is_active=True)
                                       .order_by(Software.name).all(),
    }


@bp.route('/')
@login_required
def list():
    contracts = Contract.query.filter_by(is_active=True).order_by(
        Contract.end_date.asc().nullslast()).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    contracts = text_search(contracts, q, ['name', 'reference', 'description', 'responsible'])
    contracts.sort(key=lambda c: status_rank(c.status()))
    # Cout annuel total : agrege en SQL (evite de recharger toute la table).
    from sqlalchemy import func
    total_cost = db.session.query(
        func.coalesce(func.sum(Contract.cost_yearly), 0)
    ).filter_by(is_active=True).scalar()
    contracts, page, pages, total = paginate(contracts)
    return render_template('contracts/list.html', contracts=contracts, q=q,
                           page=page, pages=pages, total=total, total_cost=total_cost,
                           kind_labels=CONTRACT_KIND_LABELS)


@bp.route('/quick-create', methods=['POST'])
@login_required
@require_edit
def quick_create():
    """Creation rapide (AJAX) d'un contrat minimal depuis un autre formulaire
    (ex. formulaire logiciel). Renvoie l'id + le nom en JSON."""
    name = (request.form.get('name', '') or '').strip()
    if not name:
        return jsonify(ok=False, error='Le nom est obligatoire.'), 400
    c = Contract(name=name, kind='maintenance', priority='medium', notice_days=0,
                 end_date=parse_date(request.form.get('end_date')))
    db.session.add(c)
    db.session.commit()
    db.session.add(ContractHistory(contract_id=c.id, action='creation',
                                   comment=f'Contrat cree : {c.name} (ajout rapide)',
                                   performed_by=current_user.username))
    db.session.commit()
    return jsonify(ok=True, id=c.id, name=c.name)


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
    return render_template('contracts/detail.html', contract=contract, histories=histories,
                           items=contract.items.all(),
                           item_kind_labels=CONTRACT_ITEM_KIND_LABELS)


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
    new_end = parse_date(request.form.get('new_end_date'))
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


# ===========================================================================
#  Pieces du marche
#
#  Une piece ne decrit qu'elle-meme : un poste, son cout, la date de son
#  document. Elle ne chiffre pas l'engagement et ne declenche rien -- c'est le
#  marche qui engage, et c'est sa date de fin qu'on surveille.
# ===========================================================================

@bp.route('/<int:id>/items/add', methods=['POST'])
@login_required
@require_edit
def item_add(id):
    contract = Contract.query.get_or_404(id)
    f = request.form
    label = (f.get('label', '') or '').strip()
    if not label:
        flash('Indiquez le poste couvert par la pièce.', 'danger')
        return redirect(url_for('contracts.detail', id=id))
    item = ContractItem(
        contract_id=contract.id, label=label,
        kind=f.get('kind') if f.get('kind') in CONTRACT_ITEM_KIND_LABELS else 'abonnement',
        cost_yearly=parse_float(f.get('cost_yearly')),
        doc_date=parse_date(f.get('doc_date')),
        notes=(f.get('notes') or None))
    db.session.add(item)
    db.session.commit()
    audit_record('ajout piece', detail=f'{contract.name} : {label}', category='contrats')
    flash('Pièce ajoutée', 'success')
    return redirect(url_for('contracts.detail', id=id))


@bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
@require_delete
def item_delete(item_id):
    item = ContractItem.query.get_or_404(item_id)
    cid, nom = item.contract_id, item.label
    db.session.delete(item)
    db.session.commit()
    audit_record('suppression piece', detail=nom, category='contrats')
    flash('Pièce supprimée', 'success')
    return redirect(url_for('contracts.detail', id=cid))


# ===========================================================================
#  Mise en concurrence : consultations et devis
#
#  Les devis racontent l'AVANT-contrat. Ils se groupent par consultation -- un
#  objet, une date -- parce qu'un logiciel en accumule plusieurs au fil des
#  annees : une liste plate ne saurait pas dire quel devis a ete retenu pour
#  quelle consultation.
# ===========================================================================

@bp.route('/consultations/<int:software_id>/add', methods=['POST'])
@login_required
@require_edit
def consultation_add(software_id):
    sw = Software.query.get_or_404(software_id)
    subject = (request.form.get('subject', '') or '').strip()
    if not subject:
        flash("Indiquez l'objet de la consultation.", 'danger')
        return redirect(url_for('software.detail', id=software_id))
    db.session.add(Consultation(software_id=sw.id, subject=subject,
                                date=parse_date(request.form.get('date')),
                                notes=(request.form.get('notes') or None)))
    db.session.commit()
    audit_record('creation consultation', detail=f'{sw.name} : {subject}', category='contrats')
    flash('Consultation ajoutée', 'success')
    return redirect(url_for('software.detail', id=software_id))


@bp.route('/consultations/<int:consultation_id>/delete', methods=['POST'])
@login_required
@require_delete
def consultation_delete(consultation_id):
    cons = Consultation.query.get_or_404(consultation_id)
    swid, objet = cons.software_id, cons.subject
    db.session.delete(cons)   # les devis suivent (cascade)
    db.session.commit()
    audit_record('suppression consultation', detail=objet, category='contrats')
    flash('Consultation supprimée', 'success')
    return redirect(url_for('software.detail', id=swid))


@bp.route('/consultations/<int:consultation_id>/quotes/add', methods=['POST'])
@login_required
@require_edit
def quote_add(consultation_id):
    cons = Consultation.query.get_or_404(consultation_id)
    f = request.form
    sid = parse_int(f.get('supplier_id'))
    nom = (f.get('supplier_name', '') or '').strip()
    if not sid and not nom:
        flash('Indiquez le fournisseur qui a remis le devis.', 'danger')
        return redirect(url_for('software.detail', id=cons.software_id))
    db.session.add(Quote(consultation_id=cons.id, supplier_id=sid,
                         supplier_name=(None if sid else nom),
                         amount=parse_float(f.get('amount')),
                         date=parse_date(f.get('date')),
                         notes=(f.get('notes') or None)))
    db.session.commit()
    flash('Devis ajouté', 'success')
    return redirect(url_for('software.detail', id=cons.software_id))


@bp.route('/quotes/<int:quote_id>/select', methods=['POST'])
@login_required
@require_edit
def quote_select(quote_id):
    """Marque le devis retenu. AU PLUS UN par consultation : les autres sont
    demarques dans le meme geste, faute de quoi deux devis retenus se
    contrediraient sans que rien ne tranche."""
    quote = Quote.query.get_or_404(quote_id)
    for autre in quote.consultation.quotes:
        autre.selected = (autre.id == quote.id)
    db.session.commit()
    audit_record('devis retenu', detail=f'{quote.consultation.subject} : {quote.who()}',
                 category='contrats')
    flash('Devis marqué comme retenu', 'success')
    return redirect(url_for('software.detail', id=quote.consultation.software_id))


@bp.route('/quotes/<int:quote_id>/delete', methods=['POST'])
@login_required
@require_delete
def quote_delete(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    swid = quote.consultation.software_id
    db.session.delete(quote)
    db.session.commit()
    flash('Devis supprimé', 'success')
    return redirect(url_for('software.detail', id=swid))
