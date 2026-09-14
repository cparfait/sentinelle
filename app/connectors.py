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

from app import db, config_store
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


def _inventory_context():
    """L'integration SoftInventory : il vient lire le parc (/api/equipment).

    Symetrique de Sesame, cle DISTINCTE : revoquer l'un ne coupe pas l'autre.
    """
    tok = current_app.config.get('INVENTORY_API_TOKEN') or ''
    masked = (tok[:6] + '…' + tok[-4:]) if len(tok) >= 12 \
        else ('•' * len(tok) if tok else '')
    endpoint = (current_app.config.get('APP_BASE_URL', '').rstrip('/') + '/api/equipment')
    return {
        'inventory_enabled': bool(current_app.config.get('INVENTORY_API_ENABLED', False)),
        'inventory_key_set': bool(tok),
        'inventory_key_masked': masked,
        'inventory_new_key': session.pop('inventory_new_key', None),
        'inventory_endpoint': endpoint,
    }


def _catalogue_context():
    """Le sens INVERSE : Sentinelle va lire le catalogue chez SoftInventory.

    La cle n'est jamais reaffichee — seulement masquee : elle est emise LA-BAS,
    et on ne la conserve que pour s'en servir.
    """
    cle = current_app.config.get('SOFTINVENTORY_KEY') or ''
    masked = (cle[:6] + '…' + cle[-4:]) if len(cle) >= 12         else ('•' * len(cle) if cle else '')
    from app.models import Software
    return {
        'catalogue_url': current_app.config.get('SOFTINVENTORY_URL', '') or '',
        'catalogue_key_set': bool(cle),
        'catalogue_key_masked': masked,
        'catalogue_refletes': Software.query.filter_by(origin='inventory').count(),
        # `is_(None)` explicite : une comparaison SQL avec NULL n'est ni vraie
        # ni fausse, et les fiches d'avant la colonne seraient invisibles. Le
        # comblement au demarrage les remplit, cette garde tient le premier
        # demarrage d'une base ancienne.
        'catalogue_locaux': Software.query.filter(
            db.or_(Software.origin.is_(None), Software.origin != 'inventory')).count(),
    }


def _webhooks_context():
    from app.models import (Webhook, WEBHOOK_CHANNELS, CONFORMITY_CATEGORIES,
                            CATEGORY_LABELS)
    return {
        'webhooks': {
            'teams': current_app.config.get('TEAMS_WEBHOOK_URL', ''),
            'slack': current_app.config.get('SLACK_WEBHOOK_URL', ''),
            'discord': current_app.config.get('DISCORD_WEBHOOK_URL', ''),
        },
        'category_webhooks': Webhook.query.order_by(Webhook.category, Webhook.channel).all(),
        'webhook_channels': WEBHOOK_CHANNELS,
        'gestion_categories': CONFORMITY_CATEGORIES,
        'conformity_labels': CATEGORY_LABELS,
    }


@bp.route('/')
@login_required
@require_admin
def index():
    ctx = _sesame_context()
    ctx.update(_inventory_context())
    ctx.update(_catalogue_context())
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


@bp.route('/softinventory', methods=['POST'])
@login_required
@require_admin
def softinventory():
    """Active/désactive le connecteur SoftInventory ou (re)génère sa clé d'API.

    Même mécanique que Sesame, clé séparée : les deux outils lisent Sentinelle
    pour des raisons différentes — l'un les habilitations, l'autre le parc — et
    doivent pouvoir être coupés indépendamment.
    """
    action = request.form.get('action', '')
    if action == 'save':
        enabled = request.form.get('inventory_enabled') == 'on'
        config_store.save({'INVENTORY_API_ENABLED': 'true' if enabled else 'false'})
        current_app.config['INVENTORY_API_ENABLED'] = enabled
        audit_record('config connecteur SoftInventory', detail=f'actif={enabled}',
                     category='preferences')
        flash('Connecteur SoftInventory ' + ('activé' if enabled else 'désactivé') + '.',
              'success')
    elif action == 'generate_key':
        key = secrets.token_urlsafe(32)
        config_store.save({'INVENTORY_API_TOKEN': key})
        current_app.config['INVENTORY_API_TOKEN'] = key
        # Affichée UNE fois via la session (champ copiable) : un flash serait
        # rendu en toast auto-disparaissant, donc non copiable.
        session['inventory_new_key'] = key
        audit_record('rotation clé API SoftInventory', category='preferences')
        flash("Nouvelle clé API SoftInventory générée — copiez-la ci-dessous, "
              "elle ne sera plus affichée.", 'success')
    return redirect(url_for('connectors.index'))


@bp.route('/catalogue', methods=['POST'])
@login_required
@require_admin
def catalogue():
    """Où lire le catalogue des applications, et l'y lire.

    SoftInventory DÉTIENT les applications ; Sentinelle en tenait une liste
    réduite, saisie une seconde fois. Trois gestes : enregistrer le connecteur,
    l'éprouver sans rien écrire, puis importer.
    """
    from app.inventory_sync import importer, lire_catalogue, previsualiser

    action = request.form.get('action', '')

    if action == 'save':
        url = (request.form.get('catalogue_url') or '').strip().rstrip('/')
        cle = (request.form.get('catalogue_key') or '').strip()
        # Le VIDE débranche : Sentinelle retrouve son catalogue local.
        if url and not url.lower().startswith(('http://', 'https://')):
            flash("L'URL doit commencer par http:// ou https://", 'danger')
            return redirect(url_for('connectors.index'))
        maj = {'SOFTINVENTORY_URL': url}
        # Clé vide = on conserve celle en place : on corrige une URL sans avoir
        # à retrouver la clé, qui n'est jamais réaffichée.
        if cle:
            maj['SOFTINVENTORY_KEY'] = cle
        config_store.save(maj)
        current_app.config.update(maj)
        audit_record('config connecteur catalogue', detail=url or '(débranché)',
                     category='preferences')
        flash('Connecteur catalogue enregistré.', 'success')

    elif action == 'test':
        apps, erreur = lire_catalogue()
        if erreur:
            flash(erreur, 'danger')
        else:
            flash(f'Connexion établie : {len(apps)} application(s) lisible(s).', 'success')

    elif action == 'preview':
        # Ce que l'import ferait, sans rien ecrire : l'ecran de comparaison
        # nomme chaque application et laisse decocher. C'est la seule porte
        # d'entree de l'import depuis l'interface.
        plan, erreur = previsualiser()
        if erreur:
            flash(erreur, 'danger')
            return redirect(url_for('connectors.index'))
        return render_template('connectors/catalogue_plan.html', plan=plan)

    elif action == 'import':
        # Les cases cochees dans l'ecran de comparaison. Une liste vide veut
        # dire « rien de retenu » — pas « tout », que porte `None`.
        retenus = [int(v) for v in request.form.getlist('retenus') if v.isdigit()]
        rapport, erreur = importer(selection=retenus)
        if erreur:
            flash(erreur, 'danger')
        else:
            parts = []
            if rapport['crees']:
                parts.append(f"{rapport['crees']} créée(s)")
            if rapport['adoptes']:
                parts.append(f"{rapport['adoptes']} rapprochée(s) d'une fiche existante")
            if rapport['actualises']:
                parts.append(f"{rapport['actualises']} actualisée(s)")
            if rapport['ecartes']:
                parts.append(f"{rapport['ecartes']} écartée(s) faute de nom")
            if rapport['ignores']:
                parts.append(f"{rapport['ignores']} laissée(s) de côté")
            if rapport['liens_poses'] or rapport['liens_retires']:
                parts.append(f"{rapport['liens_poses']} installation(s) posée(s), "
                             f"{rapport['liens_retires']} retirée(s)")
            msg = ', '.join(parts) or 'Rien à reprendre'
            # Ce qui demande un ARBITRAGE est nommé, jamais compté : un nombre
            # n'aide personne à trancher.
            if rapport['homonymes']:
                msg += f". Noms en double, seule la première est reprise : {', '.join(rapport['homonymes'])}"
            if rapport['conflits']:
                msg += f". Nom déjà tenu par une autre fiche : {', '.join(rapport['conflits'])}"
            audit_record('import du catalogue', detail=msg[:200], category='preferences')
            flash(msg + '.', 'success')

    return redirect(url_for('connectors.index'))
