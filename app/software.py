"""Inventaire des logiciels metiers : editeur (fournisseur), serveur(s)
d'installation, hebergement SaaS, contrat et suivi des mises a jour.

Onglet « Logiciels » de l'inventaire. Partage la categorie de permission
« inventory » (cf. app/decorators.py).
"""
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required
from app import db
from app.models import (Software, Supplier, Contract, Equipment, Referential,
                        HOSTING_LABELS, LIFECYCLE_LABELS, SOURCE_TYPE_LABELS,
                        AUTH_MODE_LABELS, DATA_LOCATION_LABELS)
from app.forms_util import parse_int, parse_date, status_rank
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('software', __name__)


@bp.before_request
def _guard_view():
    return view_guard('inventory')


def _reflete(sw):
    """Fiche refletee de SoftInventory, qui en detient l'identite."""
    return getattr(sw, 'origin', None) == 'inventory'


def _fill(sw, f):
    """Verse le formulaire dans la fiche.

    Sur une fiche REFLETEE, l'identite et les serveurs d'installation viennent
    de SoftInventory : les reecrire ici ne tiendrait que jusqu'au prochain
    import, qui les ecraserait sans rien dire. Seul ce qui appartient a
    Sentinelle est repris — l'editeur, le contrat, la version suivie et la
    criticite, que SoftInventory ne renseigne pas.
    """
    sw.supplier_id = parse_int(f.get('supplier_id'))
    sw.contract_id = parse_int(f.get('contract_id'))
    sw.version = (f.get('version', '') or '').strip() or None
    sw.criticality = parse_int(f.get('criticality'))
    if _reflete(sw):
        return

    sw.name = (f.get('name', '') or '').strip()
    # Hébergement : on premise / SaaS / hybride ; Docker est cumulable avec les
    # trois — un logiciel conteneurisé est hébergé QUELQUE PART, les deux
    # questions ne sont pas la même.
    sw.hosting = f.get('hosting') if f.get('hosting') in HOSTING_LABELS else 'on_premise'
    sw.is_docker = f.get('is_docker') == 'on'
    sw.internal_dev = f.get('internal_dev') == 'on'
    sw.no_server = f.get('no_server') == 'on'
    sw.lifecycle = f.get('lifecycle') if f.get('lifecycle') in LIFECYCLE_LABELS else 'production'
    sw.source_type = (f.get('source_type') if f.get('source_type') in SOURCE_TYPE_LABELS
                      else 'proprietaire')
    sw.technology_id = parse_int(f.get('technology_id'))
    # NULL = non renseigné : un défaut se serait écrit sur toute fiche créée.
    sw.auth_mode = f.get('auth_mode') if f.get('auth_mode') in AUTH_MODE_LABELS else None
    sw.auth_strong = f.get('auth_strong') == 'on'
    sw.users_count = parse_int(f.get('users_count'), minimum=0)
    sw.users_max = parse_int(f.get('users_max'), minimum=0)
    sw.service_date = parse_date(f.get('service_date'))
    sw.url = (f.get('url', '') or '').strip() or None
    sw.responsible = (f.get('responsible', '') or '').strip() or None
    sw.responsible_email = (f.get('responsible_email', '') or '').strip() or None
    sw.tech_responsible = (f.get('tech_responsible', '') or '').strip() or None
    sw.tech_responsible_email = (f.get('tech_responsible_email', '') or '').strip() or None
    sw.no_contract_note = (f.get('no_contract_note', '') or '').strip() or None
    sw.description = f.get('description') or None
    # ── Volet RGPD ──
    sw.gdpr_personal_data = f.get('gdpr_personal_data') == 'on'
    sw.gdpr_categories = (f.get('gdpr_categories', '') or '').strip() or None
    sw.gdpr_registry_ref = (f.get('gdpr_registry_ref', '') or '').strip() or None
    sw.gdpr_location = (f.get('gdpr_location') if f.get('gdpr_location') in DATA_LOCATION_LABELS
                        else 'inconnue')
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
        'technologies': Referential.options('technology'),
        'hosting_labels': HOSTING_LABELS,
        'lifecycle_labels': LIFECYCLE_LABELS,
        'source_type_labels': SOURCE_TYPE_LABELS,
        'auth_mode_labels': AUTH_MODE_LABELS,
        'data_location_labels': DATA_LOCATION_LABELS,
    }


@bp.route('/')
@login_required
def list():
    # Les fiches ECARTEES a l'import sont absentes de toutes les lectures :
    # seul l'ecran de comparaison les montre encore, pour revenir sur le refus.
    items = Software.query.filter_by(is_active=True, excluded=False).order_by(Software.name).all()
    q = request.args.get('q', '').strip()
    # Filtre par hebergement (onglets, comme le filtre par type du materiel).
    # Docker est un attribut cumulable : un logiciel conteneurise apparait aussi
    # dans son onglet d'hebergement (SaaS ou on premise).
    host = request.args.get('host', '').strip()
    total_all = len(items)
    # `hybride` compte dans LES DEUX onglets : une part est chez nous, une part
    # dehors, et l'exclure de l'un ou de l'autre cacherait la moitie de ce
    # qu'il est.
    _match = {'docker': lambda s: s.is_docker,
              'saas': lambda s: s.hosting in ('saas', 'hybride'),
              'onprem': lambda s: s.hosting in ('on_premise', 'hybride')}
    counts = {k: sum(1 for s in items if fn(s)) for k, fn in _match.items()}
    if host in _match:
        items = [s for s in items if _match[host](s)]
    from app.paging import paginate, text_search
    items = text_search(items, q, ['name', 'version', 'responsible', 'responsible_email',
                                   'tech_responsible', 'tech_responsible_email', 'description'])
    items.sort(key=lambda s: status_rank(s.computed_status()))
    items, page, pages, total = paginate(items)
    from app.inventory_sync import synchro_active
    return render_template('software/list.html', items=items, q=q, host=host,
                           counts=counts, total_all=total_all, synchro=synchro_active(),
                           page=page, pages=pages, total=total)


@bp.route('/quick-create', methods=['POST'])
@login_required
@require_edit
def quick_create():
    """Creation rapide (AJAX) d'une application/logiciel minimal depuis un autre
    formulaire (ex. revue de droits). Renvoie l'id + le nom en JSON."""
    # Meme regle que la creation pleine : tant que la synchro tourne, le
    # catalogue appartient a SoftInventory.
    from app.inventory_sync import synchro_active
    if synchro_active():
        return jsonify(ok=False, error="Catalogue synchronisé depuis SoftInventory : "
                                       "créez le logiciel là-bas."), 409
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
    # Quand la synchro tourne, le catalogue vient de SoftInventory : on n'ajoute
    # plus d'application ici. L'ecran cache deja le bouton ; ce refus-ci est
    # celui qui compte, il tient aussi pour une adresse tapee a la main.
    from app.inventory_sync import synchro_active
    if synchro_active():
        flash("Le catalogue est synchronisé depuis SoftInventory : "
              "les logiciels s'y créent.", 'warning')
        return redirect(url_for('software.list'))
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
    return render_template('software/form.html', item=item, reflete=_reflete(item),
                           **_form_context())


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

