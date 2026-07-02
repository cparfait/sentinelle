"""API JSON — endpoints légers pour le polling navigateur (session) et
l'intégration machine-to-machine avec l'outil Sesame (clé API)."""
import hmac
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from app import csrf, limiter

bp = Blueprint('api', __name__, url_prefix='/api')


def _sesame_auth_error():
    """Vérifie l'activation + la clé Bearer de l'intégration Sesame.
    Retourne une réponse d'erreur (tuple) si refusé, sinon None."""
    if not current_app.config.get('SESAME_API_ENABLED'):
        return jsonify(error='Intégration Sesame désactivée.'), 503
    token = current_app.config.get('SESAME_API_TOKEN') or ''
    if not token:
        return jsonify(error='API non configurée (clé absente).'), 503
    auth = request.headers.get('Authorization', '')
    provided = auth[7:] if auth[:7].lower() == 'bearer ' else ''
    # Comparaison à temps constant : ne fuit ni la longueur ni le préfixe.
    if not provided or not hmac.compare_digest(provided, token):
        return jsonify(error='Clé API invalide.'), 401
    return None


@bp.route('/assets')
@csrf.exempt
@limiter.limit('60 per minute')
def assets():
    """Liste des applications (catalogue) exposée à Sesame pour éviter la double
    saisie. Auth : en-tête `Authorization: Bearer <clé>`. Filtre optionnel
    `?type=application`. Réponse : tableau JSON {id, name, description, is_active}
    trié par nom (contrat attendu par Sesame)."""
    err = _sesame_auth_error()
    if err is not None:
        return err
    from app.models import Software
    # L'inventaire Logiciels métiers EST le catalogue d'applications exposé à
    # Sesame. Le filtre `type` reste accepté (compat) : seul 'application' (ou
    # absent) renvoie des données.
    atype = request.args.get('type')
    if atype and atype != 'application':
        rows = []
    else:
        rows = Software.query.filter_by(is_active=True, share_sesame=True).order_by(
            Software.name.asc()).all()
    return jsonify([
        {'id': s.id, 'name': s.name, 'description': s.description or '',
         'is_active': bool(s.is_active)}
        for s in rows
    ])


@bp.route('/alert-count')
@login_required
def alert_count():
    """Retourne le nombre d'entités en statut critique (danger) par catégorie.
    Utilisé par le polling JS pour les toasts de notification."""
    from app.models import (Account, Certificate, Domain, Backup, TestTask,
                            AccessReview, SystemUpdate, Equipment, Contract,
                            AlertSnooze)
    today = datetime.now(timezone.utc).date()
    snoozed = {}
    for s in AlertSnooze.query.filter(AlertSnooze.snoozed_until >= today).all():
        snoozed.setdefault(s.entity_type, set()).add(s.entity_id)

    def _cnt(items, statusf, etype):
        skip = snoozed.get(etype, ())
        return sum(1 for i in items if i.id not in skip and statusf(i) == 'danger')

    cats = {}
    if current_user.can_view('accounts'):
        cats['accounts'] = _cnt(Account.query.filter_by(is_active=True).all(), lambda o: o.status(), 'account')
    if current_user.can_view('certificates'):
        cats['certificates'] = _cnt(Certificate.query.filter_by(is_active=True).all(), lambda o: o.status(), 'certificate')
    if current_user.can_view('domains'):
        cats['domains'] = _cnt(Domain.query.filter_by(is_active=True).all(), lambda o: o.status(), 'domain')
    if current_user.can_view('backups'):
        cats['backups'] = _cnt(Backup.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'backup')
    if current_user.can_view('tests'):
        cats['tests'] = _cnt(TestTask.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'test')
    if current_user.can_view('reviews'):
        cats['reviews'] = _cnt(AccessReview.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'review')
    if current_user.can_view('updates'):
        cats['updates'] = _cnt(SystemUpdate.query.filter_by(is_active=True).all(), lambda o: o.status_color(), 'update')
    if current_user.can_view('inventory'):
        cats['inventory'] = _cnt(Equipment.query.filter_by(is_active=True).all(), lambda o: o.computed_status(), 'equipment')
    if current_user.can_view('contracts'):
        cats['contracts'] = _cnt(Contract.query.filter_by(is_active=True).all(), lambda o: o.status(), 'contract')

    return jsonify(danger=sum(cats.values()), by_category=cats)
