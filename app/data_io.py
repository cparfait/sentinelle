from flask import Blueprint, Response, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required
from app import csv_io
from app.decorators import require_edit, require_admin

bp = Blueprint('data_io', __name__)


@bp.route('/export-full.zip')
@login_required
@require_admin
def export_full():
    """Export total de secours (ZIP : base + CSV + page HTML + LISEZMOI)."""
    from app.full_export import build_full_export
    filename, data = build_full_export(current_app)
    return Response(data, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


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
    return _csv_response(csv_io.export_csv(key), f'sentinelle-{key}.csv')


@bp.route('/<key>/template.csv')
@login_required
def template(key):
    if not csv_io.is_valid(key):
        abort(404)
    return _csv_response(csv_io.template_csv(key), f'modele-import-{key}.csv')


@bp.route('/<key>/import', methods=['POST'])
@login_required
@require_edit
def import_csv(key):
    if not csv_io.is_valid(key):
        abort(404)
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
