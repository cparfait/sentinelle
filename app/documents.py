"""Pièces jointes : le fichier qui atteste ce que la fiche affirme.

Un marché signé, une délibération, un guide utilisateur, l'attestation d'une
autorité de certification. On les dépose sur la fiche qu'ils documentent, et on
les y retrouve — plutôt que dans un partage réseau où le lien se perd.

── Où vivent les octets ──

En BASE, dans une table à part (`DocumentContent`). Une sauvegarde de la base
est alors complète à elle seule : aucun fichier ne peut se retrouver orphelin
d'une ligne, ni une ligne d'un fichier. Et lister les pièces d'une fiche lit
des métadonnées de quelques octets, jamais les mégaoctets du contenu.

── Ce qui n'est jamais accepté du client ──

Aucun CHEMIN, aucun nom de fichier. Le téléchargement se fait par identifiant ;
le nom d'origine ne sert qu'à nommer la copie que le navigateur enregistre, et
il est nettoyé avant d'y servir. Le type MIME annoncé par le navigateur n'est
pas renvoyé tel quel : un fichier est toujours servi en pièce jointe, jamais
rendu dans la page — un HTML déposé ici ne doit pas pouvoir s'exécuter sur
l'origine de Sentinelle.

── Rien n'est imposé ──

Le module s'active depuis les Préférences, avec sa taille maximale. Désactivé,
il ne se voit nulle part et les fichiers déjà déposés restent en base.
"""
import io

from flask import (Blueprint, redirect, url_for, request, flash, abort,
                   send_file, current_app)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import Document, DocumentContent, DOCUMENT_PARENTS
from app.forms_util import parse_int
from app.audit import record as audit_record

bp = Blueprint('documents', __name__)

# Taille maximale par défaut, en mégaoctets. Une pièce jointe est un acte scanné
# ou un guide, pas une image disque : au-delà, c'est le partage réseau qu'il
# faut, et la base de Sentinelle n'a pas à l'héberger.
DEFAULT_MAX_MB = 10

# Ce qu'une DSI dépose sur une fiche : des actes scannés, des guides, des
# tableurs, des images. La liste est POSITIVE — tout ce qui n'y est pas est
# refusé — parce qu'une liste d'interdits se contourne toujours d'une extension.
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'odt', 'rtf', 'txt', 'md',
    'xls', 'xlsx', 'ods', 'csv',
    'ppt', 'pptx', 'odp',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
    'zip', '7z', 'eml', 'msg',
}


def enabled():
    """Le module est-il actif ? Défaut : oui — une pièce jointe ne coûte rien
    tant qu'on n'en dépose pas, et l'écran serait introuvable autrement."""
    return bool(current_app.config.get('DOCUMENTS_ENABLED', True))


def max_bytes():
    mo = current_app.config.get('DOCUMENT_MAX_MB') or DEFAULT_MAX_MB
    try:
        mo = int(mo)
    except (TypeError, ValueError):
        mo = DEFAULT_MAX_MB
    return max(1, mo) * 1024 * 1024


def _extension(nom):
    return nom.rsplit('.', 1)[-1].lower() if '.' in nom else ''


def for_parent(kind, parent_id):
    """Les pièces d'une fiche, la plus récente en tête — c'est le dernier acte
    versé qu'on vient chercher."""
    if kind not in DOCUMENT_PARENTS:
        return []
    col = DOCUMENT_PARENTS[kind][0]
    return (Document.query.filter(getattr(Document, col) == parent_id)
            .order_by(Document.created_at.desc()).all())


# La fiche qui PORTE la piece, et donc l'ecran ou l'on revient. Une piece de
# marche et un devis n'ont pas d'ecran a eux : ils vivent dans celui de leur
# marche et dans celui du logiciel consulte.
_ECRANS = {
    'software': 'software.detail',
    'supplier': 'suppliers.detail',
    'contract': 'contracts.detail',
    'certificate': 'certificates.detail',
    'equipment': 'inventory.detail',
}


def _retour(kind, parent_id):
    """Là d'où l'on vient. Un parent disparu ramène au tableau de bord plutôt
    qu'à une page qui n'existe plus."""
    from app.models import ContractItem, Quote
    if kind == 'contract_item':
        piece = ContractItem.query.get(parent_id) if parent_id else None
        return (url_for('contracts.detail', id=piece.contract_id) if piece
                else url_for('dashboard.index'))
    if kind == 'quote':
        devis = Quote.query.get(parent_id) if parent_id else None
        return (url_for('software.detail', id=devis.consultation.software_id) if devis
                else url_for('dashboard.index'))
    endpoint = _ECRANS.get(kind)
    return url_for(endpoint, id=parent_id) if endpoint else url_for('dashboard.index')


@bp.route('/documents/upload', methods=['POST'])
@login_required
def upload():
    if not enabled():
        abort(404)
    kind = request.form.get('parent_kind', '')
    parent_id = parse_int(request.form.get('parent_id'))
    if kind not in DOCUMENT_PARENTS or not parent_id:
        abort(400)
    col, categorie = DOCUMENT_PARENTS[kind]
    # Déposer une pièce, c'est modifier la fiche : même droit.
    if not current_user.can_edit(categorie):
        flash("Vous n'avez pas les droits pour déposer une pièce ici.", 'danger')
        return redirect(_retour(kind, parent_id))

    fichier = request.files.get('file')
    if fichier is None or not (fichier.filename or '').strip():
        flash('Choisissez un fichier.', 'danger')
        return redirect(_retour(kind, parent_id))

    nom = secure_filename(fichier.filename) or 'piece-jointe'
    ext = _extension(nom)
    if ext not in ALLOWED_EXTENSIONS:
        flash(f"Type de fichier non accepté (.{ext or '?'}). "
              f"Acceptés : {', '.join(sorted(ALLOWED_EXTENSIONS))}.", 'danger')
        return redirect(_retour(kind, parent_id))

    octets = fichier.read()
    # La taille se mesure sur les OCTETS LUS, pas sur l'en-tête annoncé : c'est
    # le seul chiffre que le client ne choisit pas.
    if not octets:
        flash('Le fichier est vide.', 'danger')
        return redirect(_retour(kind, parent_id))
    if len(octets) > max_bytes():
        flash(f'Fichier trop volumineux ({len(octets) // (1024 * 1024)} Mo) : '
              f'maximum {max_bytes() // (1024 * 1024)} Mo.', 'danger')
        return redirect(_retour(kind, parent_id))

    doc = Document(filename=nom, mime=(fichier.mimetype or '')[:128],
                   size=len(octets), uploaded_by=current_user.username,
                   category_id=parse_int(request.form.get('category_id')))
    setattr(doc, col, parent_id)
    doc.content = DocumentContent(data=octets)
    db.session.add(doc)
    db.session.commit()
    audit_record('depot piece jointe', detail=f'{nom} ({kind} #{parent_id})',
                 category=categorie)
    flash('Pièce jointe ajoutée', 'success')
    return redirect(_retour(kind, parent_id))


@bp.route('/documents/<int:id>/download')
@login_required
def download(id):
    if not enabled():
        abort(404)
    doc = Document.query.get_or_404(id)
    if not current_user.can_view(doc.permission_category()):
        abort(403)
    if doc.content is None:       # ligne sans contenu : ne devrait pas arriver
        abort(404)
    # TOUJOURS en pièce jointe, et jamais avec le type annoncé par le déposant :
    # un HTML ou un SVG rendu dans la page s'exécuterait sur l'origine de
    # Sentinelle, avec la session de qui l'ouvre.
    return send_file(io.BytesIO(doc.content.data),
                     mimetype='application/octet-stream',
                     as_attachment=True, download_name=doc.filename)


@bp.route('/documents/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not enabled():
        abort(404)
    doc = Document.query.get_or_404(id)
    categorie = doc.permission_category()
    if not current_user.can_delete(categorie):
        flash("Vous n'avez pas les droits pour retirer cette pièce.", 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))
    kind = doc.parent_kind()
    parent_id = getattr(doc, DOCUMENT_PARENTS[kind][0]) if kind else None
    nom = doc.filename
    db.session.delete(doc)        # le contenu suit (cascade)
    db.session.commit()
    audit_record('suppression piece jointe', detail=nom, category=categorie)
    flash('Pièce jointe supprimée', 'success')
    return redirect(_retour(kind, parent_id) if kind else url_for('dashboard.index'))
