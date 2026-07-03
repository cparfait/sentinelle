"""Inventaire des logiciels metiers : editeur (fournisseur), serveur(s)
d'installation, hebergement SaaS, contrat et suivi des mises a jour.

Onglet « Logiciels » de l'inventaire. Partage la categorie de permission
« inventory » (cf. app/decorators.py).
"""
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required
from app import db
from app.models import Software, Supplier, Contract, Equipment
from app.forms_util import parse_int, status_rank
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('software', __name__)


@bp.before_request
def _guard_view():
    return view_guard('inventory')


def _fill(sw, f):
    sw.name = (f.get('name', '') or '').strip()
    sw.supplier_id = parse_int(f.get('supplier_id'))
    sw.contract_id = parse_int(f.get('contract_id'))
    sw.version = (f.get('version', '') or '').strip() or None
    sw.is_saas = f.get('is_saas') == 'on'
    sw.share_sesame = f.get('share_sesame') == 'on'
    sw.url = (f.get('url', '') or '').strip() or None
    sw.criticality = parse_int(f.get('criticality'))
    sw.responsible = (f.get('responsible', '') or '').strip() or None
    sw.responsible_email = (f.get('responsible_email', '') or '').strip() or None
    sw.description = f.get('description') or None
    # Serveur(s) d'installation (multi-selection), equipements actifs uniquement.
    ids = [parse_int(v) for v in f.getlist('equipment_ids')]
    ids = [i for i in ids if i]
    sw.equipments = (Equipment.query.filter(Equipment.id.in_(ids),
                                            Equipment.is_active.is_(True)).all()
                     if ids else [])


def _form_context():
    return {
        'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all(),
        'contracts': Contract.query.filter_by(is_active=True).order_by(Contract.name).all(),
        'equipments': Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all(),
    }


@bp.route('/')
@login_required
def list():
    items = Software.query.filter_by(is_active=True).order_by(Software.name).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    items = text_search(items, q, ['name', 'version', 'responsible', 'responsible_email', 'description'])
    items.sort(key=lambda s: status_rank(s.computed_status()))
    items, page, pages, total = paginate(items)
    return render_template('software/list.html', items=items, q=q,
                           page=page, pages=pages, total=total)


@bp.route('/quick-create', methods=['POST'])
@login_required
@require_edit
def quick_create():
    """Creation rapide (AJAX) d'une application/logiciel minimal depuis un autre
    formulaire (ex. revue de droits). Renvoie l'id + le nom en JSON."""
    name = (request.form.get('name', '') or '').strip()
    if not name:
        return jsonify(ok=False, error='Le nom est obligatoire.'), 400
    sw = Software(name=name)
    db.session.add(sw)
    db.session.commit()
    audit_record('creation logiciel', detail=f'{sw.name} (ajout rapide)', category='inventory')
    return jsonify(ok=True, id=sw.id, name=sw.name)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        sw = Software()
        _fill(sw, request.form)
        if not sw.name:
            flash('Le nom du logiciel est obligatoire.', 'danger')
            return render_template('software/form.html', item=None, **_form_context())
        db.session.add(sw)
        db.session.commit()
        audit_record('creation logiciel', detail=sw.name, category='inventory')
        flash('Logiciel ajouté', 'success')
        return redirect(url_for('software.detail', id=sw.id))
    return render_template('software/form.html', item=None, **_form_context())


@bp.route('/<int:id>')
@login_required
def detail(id):
    item = Software.query.get_or_404(id)
    updates = item.system_updates.filter_by(is_active=True).all()
    return render_template('software/detail.html', item=item, updates=updates)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    item = Software.query.get_or_404(id)
    if request.method == 'POST':
        _fill(item, request.form)
        if not item.name:
            flash('Le nom du logiciel est obligatoire.', 'danger')
            return render_template('software/form.html', item=item, **_form_context())
        db.session.commit()
        audit_record('modification logiciel', detail=item.name, category='inventory')
        flash('Logiciel modifié', 'success')
        return redirect(url_for('software.detail', id=id))
    return render_template('software/form.html', item=item, **_form_context())


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    item = Software.query.get_or_404(id)
    item.is_active = False
    db.session.commit()
    audit_record('suppression logiciel', detail=item.name, category='inventory')
    flash('Logiciel supprimé', 'success')
    return redirect(url_for('software.list'))


@bp.route('/<int:id>/toggle-sesame', methods=['POST'])
@login_required
@require_edit
def toggle_sesame(id):
    """Bascule le partage d'un logiciel via l'API Sesame (depuis la liste)."""
    item = Software.query.get_or_404(id)
    item.share_sesame = not item.share_sesame
    db.session.commit()
    audit_record('partage Sesame', detail=f'{item.name}={item.share_sesame}', category='inventory')
    flash(f"« {item.name} » {'partagé avec' if item.share_sesame else 'retiré de'} Sesame.", 'success')
    return redirect(url_for('software.list'))
