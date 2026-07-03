"""Connecteurs / intégrations externes.

Espace dédié regroupant les connecteurs de Sentinelle, pensé pour accueillir les
futures intégrations. Aujourd'hui : « Sesame » (le catalogue des applications est
exposé via l'API, cf. app/api.py). L'activation/désactivation et la clé d'API sont
gérées ici (auparavant dans la page Préférences).

Réservé aux administrateurs (comme les Préférences)."""
import secrets

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, current_app)
from flask_login import login_required

from app import config_store
from app.audit import record as audit_record
from app.decorators import require_admin

bp = Blueprint('connectors', __name__, url_prefix='/connecteurs')


def _sesame_context():
    tok = current_app.config.get('SESAME_API_TOKEN') or ''
    masked = (tok[:6] + '…' + tok[-4:]) if len(tok) >= 12 \
        else ('•' * len(tok) if tok else '')
    endpoint = (current_app.config.get('APP_BASE_URL', '').rstrip('/')
                + '/api/assets?type=application')
    return {
        'sesame_enabled': bool(current_app.config.get('SESAME_API_ENABLED', False)),
        'sesame_key_set': bool(tok),
        'sesame_key_masked': masked,
        'sesame_new_key': session.pop('sesame_new_key', None),
        'sesame_endpoint': endpoint,
    }


@bp.route('/')
@login_required
@require_admin
def index():
    return render_template('connectors/index.html', **_sesame_context())


@bp.route('/sesame', methods=['POST'])
@login_required
@require_admin
def sesame():
    """Active/désactive le connecteur Sesame ou (re)génère sa clé d'API."""
    action = request.form.get('action', '')
    if action == 'save':
        enabled = request.form.get('sesame_enabled') == 'on'
        config_store.save({'SESAME_API_ENABLED': 'true' if enabled else 'false'})
        current_app.config['SESAME_API_ENABLED'] = enabled
        audit_record('config connecteur Sesame', detail=f'actif={enabled}', category='preferences')
        flash('Connecteur Sesame ' + ('activé' if enabled else 'désactivé') + '.', 'success')
    elif action == 'generate_key':
        key = secrets.token_urlsafe(32)
        config_store.save({'SESAME_API_TOKEN': key})
        current_app.config['SESAME_API_TOKEN'] = key
        # Affichée UNE fois via la session (champ copiable) : un flash serait rendu
        # en toast auto-disparaissant, donc non copiable.
        session['sesame_new_key'] = key
        audit_record('rotation clé API Sesame', category='preferences')
        flash("Nouvelle clé API Sesame générée — copiez-la ci-dessous, elle ne sera plus affichée.", 'success')
    return redirect(url_for('connectors.index'))
