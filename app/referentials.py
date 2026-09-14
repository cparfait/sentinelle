"""Listes de valeurs administrables : technologies applicatives, catégories de
pièces jointes, types de tâches — et l'annuaire des services utilisateurs.

── Ce qui est ici, et ce qui n'y est pas ──

Seulement des libellés purement DESCRIPTIFS. Les valeurs dont un calcul dépend
— le cycle de vie d'un logiciel, l'hébergement, la criticité, le statut d'un
certificat — restent des constantes du code : pouvoir en ajouter ou en
supprimer laisserait des fiches orphelines et des filtres qui ne filtrent plus.
Une valeur qu'on peut ajouter est une valeur dont aucun calcul ne dépend.

Les services utilisateurs y figurent parce qu'on les administre au même endroit,
mais ils ont leur table : un service porte un référent, avec son adresse et son
téléphone, qu'une simple liste de libellés ne saurait pas tenir.
"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required

from app import db
from app.models import Referential, UserService, REFERENTIAL_KINDS
from app.decorators import require_admin
from app.forms_util import parse_int
from app.audit import record as audit_record

bp = Blueprint('referentials', __name__)


@bp.route('/referentiels')
@login_required
@require_admin
def index():
    listes = {kind: Referential.query.filter_by(kind=kind)
                                     .order_by(Referential.position, Referential.label).all()
              for kind in REFERENTIAL_KINDS}
    services = (UserService.query.order_by(UserService.position, UserService.name).all())
    return render_template('referentials/index.html', listes=listes,
                           kind_labels=REFERENTIAL_KINDS, services=services)


@bp.route('/referentiels/add', methods=['POST'])
@login_required
@require_admin
def add():
    kind = request.form.get('kind', '')
    label = (request.form.get('label', '') or '').strip()
    if kind not in REFERENTIAL_KINDS or not label:
        flash('Indiquez un libellé.', 'danger')
        return redirect(url_for('referentials.index'))
    # Le doublon est REFUSE plutot qu'ignore : deux libelles identiques dans une
    # liste deroulante ne se distinguent pas, et celui qui vient de le saisir
    # doit savoir qu'il existait deja.
    if Referential.query.filter_by(kind=kind, label=label).first():
        flash(f'« {label} » existe déjà dans cette liste.', 'warning')
        return redirect(url_for('referentials.index'))
    position = parse_int(request.form.get('position'), 0, minimum=0)
    db.session.add(Referential(kind=kind, label=label, position=position))
    db.session.commit()
    audit_record('ajout referentiel', detail=f'{REFERENTIAL_KINDS[kind]} : {label}',
                 category='preferences')
    flash('Valeur ajoutée', 'success')
    return redirect(url_for('referentials.index'))


@bp.route('/referentiels/<int:id>/delete', methods=['POST'])
@login_required
@require_admin
def delete(id):
    """Retire la valeur de la liste. Les fiches qui la portaient gardent leur
    référence : SQLite ne casse rien, et l'écran affiche simplement un vide —
    perdre la qualification de cinquante logiciels parce qu'on a rangé une
    liste serait pire que de laisser une valeur retirée finir de vivre sur les
    fiches qui l'avaient déjà."""
    item = Referential.query.get_or_404(id)
    libelle, kind = item.label, item.kind
    db.session.delete(item)
    db.session.commit()
    audit_record('suppression referentiel',
                 detail=f'{REFERENTIAL_KINDS.get(kind, kind)} : {libelle}',
                 category='preferences')
    flash('Valeur supprimée', 'success')
    return redirect(url_for('referentials.index'))


# ═══════════════════════════════════════════════════════════════════════════
#  Services utilisateurs
# ═══════════════════════════════════════════════════════════════════════════

@bp.route('/referentiels/services/add', methods=['POST'])
@login_required
@require_admin
def service_add():
    name = (request.form.get('name', '') or '').strip()
    if not name:
        flash('Indiquez le nom du service.', 'danger')
        return redirect(url_for('referentials.index'))
    if UserService.query.filter_by(name=name).first():
        flash(f'Le service « {name} » existe déjà.', 'warning')
        return redirect(url_for('referentials.index'))
    db.session.add(UserService(
        name=name,
        contact_name=(request.form.get('contact_name', '') or '').strip() or None,
        contact_email=(request.form.get('contact_email', '') or '').strip() or None,
        contact_phone=(request.form.get('contact_phone', '') or '').strip() or None,
        position=parse_int(request.form.get('position'), 0, minimum=0)))
    db.session.commit()
    audit_record('creation service utilisateur', detail=name, category='preferences')
    flash('Service ajouté', 'success')
    return redirect(url_for('referentials.index'))


@bp.route('/referentiels/services/<int:id>/edit', methods=['POST'])
@login_required
@require_admin
def service_edit(id):
    sv = UserService.query.get_or_404(id)
    name = (request.form.get('name', '') or '').strip()
    if name:
        sv.name = name
    sv.contact_name = (request.form.get('contact_name', '') or '').strip() or None
    sv.contact_email = (request.form.get('contact_email', '') or '').strip() or None
    sv.contact_phone = (request.form.get('contact_phone', '') or '').strip() or None
    db.session.commit()
    audit_record('modification service utilisateur', detail=sv.name, category='preferences')
    flash('Service modifié', 'success')
    return redirect(url_for('referentials.index'))


@bp.route('/referentiels/services/<int:id>/delete', methods=['POST'])
@login_required
@require_admin
def service_delete(id):
    """Désactive plutôt que supprimer : le service disparaît des listes
    déroulantes, mais les certificats et les logiciels qui le nommaient
    continuent de l'afficher. Un service se réorganise ; l'historique de ce
    qu'il utilisait, non."""
    sv = UserService.query.get_or_404(id)
    sv.is_active = False
    db.session.commit()
    audit_record('suppression service utilisateur', detail=sv.name, category='preferences')
    flash('Service retiré des listes', 'success')
    return redirect(url_for('referentials.index'))
