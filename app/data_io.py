import os
import shutil

from flask import (Blueprint, Response, redirect, url_for, request, flash, abort,
                   current_app, send_file)
from flask_login import login_required, current_user
from app import csv_io
from app.decorators import require_admin

bp = Blueprint('data_io', __name__)


@bp.route('/export-full.zip')
@login_required
@require_admin
def export_full():
    """Export total de secours (ZIP : base + CSV + page HTML + LISEZMOI).

    `?sans_documents=1` retire les octets des pieces jointes : quelques
    centaines de mega-octets tombent a quelques centaines de kilo-octets.

    L'archive est un FICHIER temporaire, envoye en flux puis supprime quand la
    reponse est close — pas avant : sous Windows, un fichier encore ouvert ne
    se supprime pas, et l'export echouerait apres avoir tout construit.
    """
    from app.full_export import build_full_export
    sans_documents = request.args.get('sans_documents') in ('1', 'true', 'on')
    filename, chemin = build_full_export(current_app, sans_documents=sans_documents)
    reponse = send_file(chemin, mimetype='application/zip',
                        as_attachment=True, download_name=filename,
                        conditional=False)
    reponse.call_on_close(
        lambda: shutil.rmtree(os.path.dirname(chemin), ignore_errors=True))
    return reponse


def _csv_response(content, filename):
    return Response(
        content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@bp.route('/<key>/export.csv')
@login_required
def export(key):
    if not csv_io.is_valid(key):
        abort(404)
    if not current_user.can_view(key):
        abort(403)
    return _csv_response(csv_io.export_csv(key), f'sentinelle-{key}.csv')


@bp.route('/<key>/template.csv')
@login_required
def template(key):
    if not csv_io.is_valid(key):
        abort(404)
    if not current_user.can_view(key):
        abort(403)
    return _csv_response(csv_io.template_csv(key), f'modele-import-{key}.csv')


@bp.route('/<key>/import', methods=['POST'])
@login_required
def import_csv(key):
    if not csv_io.is_valid(key):
        abort(404)
    if not current_user.can_edit(key):
        flash("Vous n'avez pas les droits pour importer dans cette categorie.", 'danger')
        return redirect(url_for(csv_io.SPECS[key]['list_endpoint']))
    endpoint = csv_io.SPECS[key]['list_endpoint']
    file = request.files.get('file')
    if not file or not file.filename:
        flash('Aucun fichier fourni.', 'danger')
        return redirect(url_for(endpoint))
    try:
        created, errors = csv_io.import_csv(key, file.read())
    except Exception as e:
        flash(f"Import impossible : {e}", 'danger')
        return redirect(url_for(endpoint))
    if created:
        flash(f"{created} enregistrement(s) importe(s).", 'success')
    if errors:
        flash(f"{len(errors)} ligne(s) en erreur : " + ' | '.join(errors[:5]), 'warning')
    if not created and not errors:
        flash("Aucune ligne importee (fichier vide ou colonnes non reconnues).", 'info')
    return redirect(url_for(endpoint))
