"""Connecteurs / intégrations externes.

Espace dédié regroupant les connecteurs de Sentinelle, pensé pour accueillir les
futures intégrations. Aujourd'hui : « Sesame » (le catalogue des applications est
exposé via l'API, cf. app/api.py) et « chatIA » (l'assistant IA de la Ville lit
les échéances suivies, en lecture seule, cf. app/suivi.py). L'activation/
désactivation et la clé d'API de chacun sont gérées ici (auparavant dans la page
Préférences).

Réservé aux administrateurs (comme les Préférences)."""
import secrets

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, current_app)
from flask_login import login_required

from app import db, config_store
from app.audit import record as audit_record
from app.decorators import require_admin

bp = Blueprint('connectors', __name__, url_prefix='/connecteurs')


# Connecteurs machine-à-machine : préfixe des variables du gabarit -> (nom
# affiché, clé d'activation, clé de l'API, adresse à donner à l'outil). Le même
# mécanisme pour chacun, une clé par outil : couper l'un ne coupe pas l'autre.
_CARTES_API = {
    'sesame': ('Sesame', 'SESAME_API_ENABLED', 'SESAME_API_TOKEN', '/api/assets?type=application'),
    # chatIA ajoute lui-même les chemins /api/chatia/… : on lui donne l'adresse
    # de Sentinelle, rien de plus.
    'chatia': ('chatIA', 'CHATIA_API_ENABLED', 'CHATIA_API_TOKEN', ''),
}


def _carte_context(prefixe):
    _nom, cle_active, cle_token, chemin = _CARTES_API[prefixe]
    tok = current_app.config.get(cle_token) or ''
    masked = (tok[:6] + '…' + tok[-4:]) if len(tok) >= 12 \
        else ('•' * len(tok) if tok else '')
    endpoint = current_app.config.get('APP_BASE_URL', '').rstrip('/') + chemin
    return {
        f'{prefixe}_enabled': bool(current_app.config.get(cle_active, False)),
        f'{prefixe}_key_set': bool(tok),
        f'{prefixe}_key_masked': masked,
        f'{prefixe}_new_key': session.pop(f'{prefixe}_new_key', None),
        f'{prefixe}_endpoint': endpoint,
    }


def _sesame_context():
    return _carte_context('sesame')


def _webhooks_context():
    from app.models import (Webhook, WEBHOOK_CHANNELS, WEBHOOK_CATEGORIES,
                            CATEGORY_LABELS)
    return {
        'webhooks': {
            'teams': current_app.config.get('TEAMS_WEBHOOK_URL', ''),
            'slack': current_app.config.get('SLACK_WEBHOOK_URL', ''),
            'discord': current_app.config.get('DISCORD_WEBHOOK_URL', ''),
        },
        'category_webhooks': Webhook.query.order_by(Webhook.category, Webhook.channel).all(),
        'webhook_channels': WEBHOOK_CHANNELS,
        'gestion_categories': WEBHOOK_CATEGORIES,
        'conformity_labels': CATEGORY_LABELS,
    }


@bp.route('/')
@login_required
@require_admin
def index():
    ctx = _sesame_context()
    ctx.update(_carte_context('chatia'))
    ctx.update(_webhooks_context())
    return render_template('connectors/index.html', **ctx)


@bp.route('/webhooks', methods=['POST'])
@login_required
@require_admin
def webhooks():
    """Webhooks de notification (Teams/Slack/Discord) : URLs globales, tests, et
    webhooks par catégorie (ajout/suppression/test)."""
    action = request.form.get('action', '')
    if action == 'save_webhooks':
        mapping = {
            'TEAMS_WEBHOOK_URL': request.form.get('teams_webhook', '').strip(),
            'SLACK_WEBHOOK_URL': request.form.get('slack_webhook', '').strip(),
            'DISCORD_WEBHOOK_URL': request.form.get('discord_webhook', '').strip(),
        }
        config_store.save(mapping)
        current_app.config.update(mapping)
        audit_record('config notifications', category='preferences')
        flash('Notifications enregistrées', 'success')

    elif action in ('test_teams', 'test_slack', 'test_discord'):
        from app import notify
        fn = {'test_teams': notify.send_teams, 'test_slack': notify.send_slack,
              'test_discord': notify.send_discord}[action]
        ok = fn('Test de notification', 'Notification de test depuis Sentinelle.',
                status='info', url=current_app.config.get('APP_BASE_URL'))
        canal = action.split('_')[1].capitalize()
        flash(f'Notification {canal} envoyée.' if ok else f"Échec de l'envoi {canal} (URL invalide ?).",
              'success' if ok else 'danger')

    elif action == 'add_webhook':
        from app.models import Webhook, WEBHOOK_CHANNELS, CATEGORY_LABELS
        channel = request.form.get('wh_channel', '')
        url = request.form.get('wh_url', '').strip()
        category = request.form.get('wh_category', 'all')
        if channel not in WEBHOOK_CHANNELS:
            flash('Canal invalide.', 'danger')
        elif not url:
            flash("L'URL du webhook est obligatoire.", 'danger')
        elif not url.lower().startswith('https://'):
            # Limite le risque de SSRF / d'exfiltration vers un hôte interne :
            # les webhooks Teams/Slack/Discord sont tous en HTTPS.
            flash('L\'URL du webhook doit commencer par https://', 'danger')
        else:
            if category != 'all' and category not in CATEGORY_LABELS:
                category = 'all'
            db.session.add(Webhook(category=category, channel=channel, url=url,
                                   label=request.form.get('wh_label', '').strip() or None))
            db.session.commit()
            audit_record('ajout webhook', detail=f'{channel} / {category}', category='preferences')
            flash('Webhook ajouté', 'success')

    elif action == 'delete_webhook':
        from app.models import Webhook
        w = db.session.get(Webhook, request.form.get('wh_id', type=int))
        if w:
            db.session.delete(w)
            db.session.commit()
            audit_record('suppression webhook', detail=f'{w.channel} / {w.category}', category='preferences')
            flash('Webhook supprimé', 'success')

    elif action == 'test_webhook':
        from app.models import Webhook
        from app.notify import send_to
        w = db.session.get(Webhook, request.form.get('wh_id', type=int))
        if w:
            ok = send_to(w.channel, w.url, 'Test de notification',
                         'Ceci est un message de test depuis Sentinelle.', status='info',
                         url=current_app.config.get('APP_BASE_URL'))
            flash('Test envoyé.' if ok else "Échec de l'envoi du test.",
                  'success' if ok else 'danger')
    return redirect(url_for('connectors.index'))


@bp.route('/sesame', methods=['POST'])
@login_required
@require_admin
def sesame():
    """Active/désactive le connecteur Sesame ou (re)génère sa clé d'API."""
    return _regler_carte('sesame')


@bp.route('/chatia', methods=['POST'])
@login_required
@require_admin
def chatia():
    """Active/désactive le connecteur chatIA ou (re)génère sa clé d'API."""
    return _regler_carte('chatia')


def _regler_carte(prefixe):
    nom, cle_active, cle_token, _chemin = _CARTES_API[prefixe]
    action = request.form.get('action', '')
    if action == 'save':
        enabled = request.form.get(f'{prefixe}_enabled') == 'on'
        config_store.save({cle_active: 'true' if enabled else 'false'})
        current_app.config[cle_active] = enabled
        audit_record(f'config connecteur {nom}', detail=f'actif={enabled}', category='preferences')
        flash(f'Connecteur {nom} ' + ('activé' if enabled else 'désactivé') + '.', 'success')
    elif action == 'generate_key':
        key = secrets.token_urlsafe(32)
        config_store.save({cle_token: key})
        current_app.config[cle_token] = key
        # Affichée UNE fois via la session (champ copiable) : un flash serait rendu
        # en toast auto-disparaissant, donc non copiable.
        session[f'{prefixe}_new_key'] = key
        audit_record(f'rotation clé API {nom}', category='preferences')
        flash(f"Nouvelle clé API {nom} générée — copiez-la ci-dessous, elle ne sera plus affichée.",
              'success')
    return redirect(url_for('connectors.index'))
