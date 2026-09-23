"""Inventaire des logiciels metiers : editeur (fournisseur), serveur(s)
d'installation, hebergement SaaS, contrat et suivi des mises a jour.

Onglet « Logiciels » de l'inventaire. Partage la categorie de permission
« inventory » (cf. app/decorators.py).
"""
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify)
from flask_login import login_required
from app import db
from app import features
from app.models import (Software, Supplier, Contract, Equipment, Referential,
                        UserService, SoftwareLink, SoftwareShare,
                        HOSTING_LABELS, LIFECYCLE_LABELS, SOURCE_TYPE_LABELS,
                        AUTH_MODE_LABELS, DATA_LOCATION_LABELS)
from app.forms_util import parse_int, parse_date, status_rank
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('software', __name__)


@bp.before_request
def _guard_view():
    return view_guard('inventory')


def _fill(sw, f):
    """Verse le formulaire dans la fiche."""
    sw.supplier_id = parse_int(f.get('supplier_id'))
    # Marches couvrant ce logiciel (M:N). Le rattachement se pose des deux
    # cotes -- ici et sur la fiche du marche : c'est la MEME table, et obliger a
    # passer par l'un des deux ecrans n'aurait servi qu'a le faire chercher.
    cids = [parse_int(v) for v in f.getlist('contract_ids')]
    cids = [i for i in cids if i]
    sw.contracts = (Contract.query.filter(Contract.id.in_(cids),
                                          Contract.is_active.is_(True)).all()
                    if cids else [])
    sw.version = (f.get('version', '') or '').strip() or None
    sw.criticality = parse_int(f.get('criticality'))
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
    # ── Volet RGPD ── Module coupe : le formulaire ne porte pas ces champs,
    # et les lire effacerait ce qui avait ete saisi avant.
    if features.enabled('gdpr'):
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
    # Services utilisateurs : les directions qui s'en servent. Un logiciel en
    # sert souvent plusieurs, et une direction en utilise plusieurs.
    svids = [parse_int(v) for v in f.getlist('user_service_ids')]
    svids = [i for i in svids if i]
    sw.user_services = (UserService.query.filter(UserService.id.in_(svids),
                                                 UserService.is_active.is_(True)).all()
                        if svids else [])


def _form_context():
    return {
        'suppliers': Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all(),
        'contracts': Contract.query.filter_by(is_active=True).order_by(Contract.name).all(),
        'equipments': Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all(),
        'technologies': Referential.options('technology'),
        'user_services': UserService.options(),
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
    items = Software.query.filter_by(is_active=True).order_by(Software.name).all()
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
    return render_template('software/list.html', items=items, q=q, host=host,
                           counts=counts, total_all=total_all,
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
        # Le nom se verifie AVANT de toucher a la session : une fiche sans nom
        # n'a pas a y entrer, ne serait-ce qu'en attente.
        if not (request.form.get('name', '') or '').strip():
            flash('Le nom du logiciel est obligatoire.', 'danger')
            return render_template('software/form.html', item=None, **_form_context())
        sw = Software(name=(request.form.get('name') or '').strip())
        # Rattache a la session AVANT le remplissage : poser les marches d'une
        # fiche qui n'y est pas encore laisserait le lien de cote sans rien dire
        # -- SQLAlchemy se contente d'un avertissement.
        db.session.add(sw)
        _fill(sw, request.form)
        db.session.commit()
        audit_record('creation logiciel', detail=sw.name, category='inventory')
        flash('Logiciel ajouté', 'success')
        return redirect(url_for('software.detail', id=sw.id))
    return render_template('software/form.html', item=None, **_form_context())


def _marches_rattachables(item):
    """Les marches qu'on peut rattacher a cette fiche.

    Les marches ont ete saisis au nom de la SOCIETE qui les signe, pas de
    l'application qu'ils couvrent : la fiche logiciel affichait donc « Aucun
    contrat » alors que l'acte existait, range sous son editeur. La liste
    propose donc ceux de son editeur -- la famille a laquelle il appartient --
    et ceux que personne ne couvre encore, qui n'attendent qu'une fiche.

    Un logiciel sans editeur (developpement interne) n'a pas de famille : il ne
    lui reste que les orphelins.
    """
    deja = {c.id for c in item.contracts}
    candidats = []
    for c in Contract.query.filter(Contract.is_active.is_(True)).order_by(Contract.name).all():
        if c.id in deja:
            continue
        if (item.supplier_id and c.supplier_id == item.supplier_id) or not c.software:
            candidats.append(c)
    return candidats


@bp.route('/<int:id>')
@login_required
def detail(id):
    item = Software.query.get_or_404(id)
    updates = item.system_updates.filter_by(is_active=True).all()
    # Les marches se lisent du plus lointain au plus proche : celui qui court
    # encore est celui qu'on vient verifier, et il vient en tete.
    marches = sorted(item.contracts.filter_by(is_active=True).all(),
                     key=lambda c: (c.end_date is not None, c.end_date), reverse=True)
    # Les consultations se lisent de la plus RECENTE a la plus ancienne : c'est
    # celle qui a abouti au marche en cours qu'on vient verifier.
    from app.models import Consultation
    consultations = item.consultations.order_by(
        Consultation.date.desc().nullslast(), Consultation.id.desc()).all()
    # Les deux sens du flux, separes : savoir que la paie alimente la
    # comptabilite, et non l'inverse, est tout l'interet de la ligne.
    autres = (Software.query.filter(Software.is_active.is_(True),
                                    Software.id != item.id)
              .order_by(Software.name).all())
    from app.documents import enabled as documents_actifs, inherited_for_software
    return render_template('software/detail.html', item=item, updates=updates,
                           consultations=consultations, marches=marches,
                           marches_rattachables=_marches_rattachables(item),
                           pieces_heritees=(inherited_for_software(item)
                                            if documents_actifs() else []),
                           sortants=item.links_out.all(), entrants=item.links_in.all(),
                           partages=item.shares.order_by(SoftwareShare.label).all(),
                           autres_logiciels=autres,
                           taches=item.tasks.filter_by(is_active=True).all(),
                           suppliers=Supplier.query.filter_by(is_active=True)
                                                   .order_by(Supplier.name).all())


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



# ═══════════════════════════════════════════════════════════════════════════
#  Interconnexions : les flux entre logiciels
# ═══════════════════════════════════════════════════════════════════════════

@bp.route('/<int:id>/links/add', methods=['POST'])
@login_required
@require_edit
def link_add(id):
    features.require('links')
    """Declare un flux SORTANT depuis cette fiche. Le sens est porte par la
    ligne ; la fiche d'en face le verra comme entrant, sans qu'on ait a le
    saisir deux fois."""
    sw = Software.query.get_or_404(id)
    cible_id = parse_int(request.form.get('target_id'))
    cible = Software.query.get(cible_id) if cible_id else None
    if cible is None:
        flash('Choisissez le logiciel destinataire du flux.', 'danger')
        return redirect(url_for('software.detail', id=id))
    if cible.id == sw.id:
        # Un flux d'un logiciel vers lui-meme ne decrit rien.
        flash("Un logiciel ne peut pas alimenter lui-même.", 'danger')
        return redirect(url_for('software.detail', id=id))
    if SoftwareLink.query.filter_by(source_id=sw.id, target_id=cible.id).first():
        flash('Ce flux est déjà déclaré.', 'warning')
        return redirect(url_for('software.detail', id=id))
    db.session.add(SoftwareLink(
        source_id=sw.id, target_id=cible.id,
        description=(request.form.get('description', '') or '').strip() or None))
    db.session.commit()
    audit_record('ajout interconnexion', detail=f'{sw.name} -> {cible.name}',
                 category='inventory')
    flash('Flux ajouté', 'success')
    return redirect(url_for('software.detail', id=id))


@bp.route('/links/<int:link_id>/delete', methods=['POST'])
@login_required
@require_delete
def link_delete(link_id):
    features.require('links')
    lien = SoftwareLink.query.get_or_404(link_id)
    # On revient sur la fiche d'ou l'on a clique, qui n'est pas toujours la
    # source : les deux sens s'affichent et se retirent des deux cotes.
    retour = parse_int(request.form.get('from_id')) or lien.source_id
    detail = f'{lien.source.name} -> {lien.target.name}'
    db.session.delete(lien)
    db.session.commit()
    audit_record('suppression interconnexion', detail=detail, category='inventory')
    flash('Flux supprimé', 'success')
    return redirect(url_for('software.detail', id=retour))


# ═══════════════════════════════════════════════════════════════════════════
#  Partages reseau
#
#  Le chemin est AFFICHE et COPIE, jamais ouvert : un navigateur refuse de
#  suivre un lien `file://` pose par une page servie en http(s) -- le clic ne
#  ferait rien, sans meme un message. C'est a l'Explorateur de l'ouvrir.
# ═══════════════════════════════════════════════════════════════════════════

@bp.route('/<int:id>/shares/add', methods=['POST'])
@login_required
@require_edit
def share_add(id):
    sw = Software.query.get_or_404(id)
    chemin = (request.form.get('path', '') or '').strip()
    if not chemin:
        flash('Indiquez le chemin du dossier.', 'danger')
        return redirect(url_for('software.detail', id=id))
    if SoftwareShare.query.filter_by(software_id=sw.id, path=chemin).first():
        # Le meme dossier deux fois sur la meme fiche n'apprend rien a personne.
        flash('Ce dossier est déjà rattaché à cette fiche.', 'warning')
        return redirect(url_for('software.detail', id=id))
    db.session.add(SoftwareShare(
        software_id=sw.id, path=chemin[:512],
        label=(request.form.get('label', '') or '').strip() or None))
    db.session.commit()
    audit_record('ajout partage reseau', detail=f'{sw.name} : {chemin}', category='inventory')
    flash('Dossier ajouté', 'success')
    return redirect(url_for('software.detail', id=id))


@bp.route('/shares/<int:share_id>/delete', methods=['POST'])
@login_required
@require_delete
def share_delete(share_id):
    partage = SoftwareShare.query.get_or_404(share_id)
    swid, chemin = partage.software_id, partage.path
    db.session.delete(partage)
    db.session.commit()
    audit_record('suppression partage reseau', detail=chemin, category='inventory')
    flash('Dossier retiré', 'success')
    return redirect(url_for('software.detail', id=swid))
