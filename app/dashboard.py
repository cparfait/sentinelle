from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.models import (Account, Certificate, Backup, BackupCheck, TestTask,
                        AlertLog, Domain, AccessReview, SystemUpdate, Equipment,
                        Contract)
from app import db

bp = Blueprint('dashboard', __name__)

# ---------------------------------------------------------------------------
# Tableau de bord personnalisable (par utilisateur)
# ---------------------------------------------------------------------------
# Chaque bloc du dashboard est un « widget » identifie par une cle stable.
# L'ordre et la visibilite sont propres a chaque utilisateur (User.dashboard_prefs,
# JSON). La resolution ci-dessous tolere l'ajout de nouveaux blocs (visibles par
# defaut, en fin de liste) et le retrait d'anciens (ignores). `span` = largeur en
# colonnes sur une grille a 12 colonnes.
DASHBOARD_WIDGETS = [
    {'key': 'conformity',    'label': 'Conformité globale',              'icon': 'bi-speedometer2',       'span': 12},
    {'key': 'stats',         'label': 'Vignettes de synthèse',           'icon': 'bi-grid-3x3-gap',       'span': 12},
    {'key': 'backups_today', 'label': 'Validation des backups du jour',  'icon': 'bi-cloud-arrow-up',     'span': 12},
    {'key': 'attention',     'label': 'Éléments requérant votre attention', 'icon': 'bi-exclamation-triangle', 'span': 12},
    {'key': 'upcoming',      'label': 'À venir',                         'icon': 'bi-calendar-event',     'span': 6},
    {'key': 'alerts',        'label': 'Dernières alertes',               'icon': 'bi-bell',               'span': 6},
]


# Largeur par defaut de chaque bloc (colonnes sur une grille a 12). Bornes de
# redimensionnement cote client ET serveur : min 3 (un quart), max 12 (pleine).
WIDGET_SPAN_DEFAULT = {w['key']: w['span'] for w in DASHBOARD_WIDGETS}
WIDGET_SPAN_MIN = 3
WIDGET_SPAN_MAX = 12

# Vignettes de synthese (bloc « stats ») : cle stable, categorie de droit (pour
# le filtrage can_view), et rendu (endpoint/libelle/icone/couleur + libelles de
# legende specifiques). L'ordre est personnalisable par utilisateur, comme les
# blocs. `cat` = categorie de permission ; `key` sert d'identifiant d'ordre.
STAT_CARDS = [
    {'key': 'accounts',     'cat': 'accounts',     'label': 'Comptes',         'icon': 'bi-key',               'color': '#6366f1', 'endpoint': 'accounts.list'},
    {'key': 'certificates', 'cat': 'certificates', 'label': 'Certificats',     'icon': 'bi-award',             'color': '#10b981', 'endpoint': 'certificates.list'},
    {'key': 'domains',      'cat': 'domains',      'label': 'Domaines',        'icon': 'bi-globe',             'color': '#3b82f6', 'endpoint': 'domains.list'},
    {'key': 'backups',      'cat': 'backups',      'label': 'Backups',         'icon': 'bi-cloud-arrow-up',    'color': '#06b6d4', 'endpoint': 'backups.list',     'danger_label': 'échoué(s)'},
    {'key': 'tests',        'cat': 'tests',        'label': 'Tests',           'icon': 'bi-clipboard-check',   'color': '#f59e0b', 'endpoint': 'tests.list',       'danger_label': 'en retard'},
    {'key': 'reviews',      'cat': 'reviews',      'label': 'Revue de droits', 'icon': 'bi-person-check',      'color': '#8b5cf6', 'endpoint': 'reviews.list'},
    {'key': 'updates',      'cat': 'updates',      'label': 'Mises à jour',    'icon': 'bi-arrow-up-circle',   'color': '#ec4899', 'endpoint': 'updates.list',     'ok_label': 'à jour', 'warning_label': 'dispo'},
    {'key': 'inventory',    'cat': 'inventory',    'label': 'Inventaire',      'icon': 'bi-hdd-stack',         'color': '#0ea5e9', 'endpoint': 'inventory.list'},
    {'key': 'contracts',    'cat': 'contracts',    'label': 'Contrats',        'icon': 'bi-file-earmark-text', 'color': '#14b8a6', 'endpoint': 'contracts.list',   'danger_label': 'à traiter'},
]


def resolve_card_order(user, available):
    """Ordre des vignettes de synthese pour `user`. Meme logique que les blocs :
    l'ordre enregistre est filtre sur les vignettes disponibles (droits), et toute
    vignette disponible non mentionnee est ajoutee a la fin (ordre de reference)."""
    avail = [k for k in available]
    avail_set = set(avail)
    saved = [k for k in _load_prefs(user).get('cards', []) if k in avail_set]
    seen = set(saved)
    return saved + [k for k in avail if k not in seen]


def _load_prefs(user):
    """Charge et decode les preferences dashboard de l'utilisateur (dict, jamais None)."""
    import json
    if user.dashboard_prefs:
        try:
            return json.loads(user.dashboard_prefs) or {}
        except (ValueError, TypeError):
            return {}
    return {}


def resolve_widget_spans(user):
    """Largeur effective (colonnes) de chaque bloc : defaut du registre, ecrase
    par la preference utilisateur si valide (bornee a [MIN, MAX])."""
    spans = dict(WIDGET_SPAN_DEFAULT)
    saved = _load_prefs(user).get('spans')
    for key, val in (saved if isinstance(saved, dict) else {}).items():
        if key not in spans:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if WIDGET_SPAN_MIN <= n <= WIDGET_SPAN_MAX:
            spans[key] = n
    return spans


def resolve_dashboard_layout(user, available):
    """Calcule (visibles, masques) pour `user` a partir de ses preferences.

    `available` : liste ordonnee des cles de blocs pertinents pour cet utilisateur
    (selon droits et donnees). Les preferences enregistrees sont filtrees sur cet
    ensemble ; tout bloc disponible non mentionne est considere visible (defaut sur)
    et ajoute a la fin dans l'ordre de reference."""
    prefs = _load_prefs(user)
    avail = [k for k in available]
    avail_set = set(avail)
    hidden = [k for k in prefs.get('hidden', []) if k in avail_set]
    hidden_set = set(hidden)
    saved_visible = [k for k in prefs.get('order', []) if k in avail_set and k not in hidden_set]
    seen = set(saved_visible) | hidden_set
    tail = [k for k in avail if k not in seen]  # nouveaux blocs -> visibles par defaut
    visible = saved_visible + tail
    return visible, hidden


@bp.route('/healthz')
def healthz():
    """Sonde de supervision (Zabbix/Centreon/NinjaOne...), sans authentification.
    Verifie que l'app repond, que la base est accessible et que le scheduler a
    execute au moins un job dans les dernieres 26 h. 200 = OK, 503 = probleme.
    N'expose volontairement aucun detail metier."""
    from flask import jsonify
    from app.models import SchedulerRun
    out = {'app': 'ok', 'database': 'ok', 'scheduler': 'ok'}
    code = 200
    try:
        last = SchedulerRun.query.order_by(SchedulerRun.run_at.desc()).first()
    except Exception:
        out['database'] = 'error'
        out['scheduler'] = 'unknown'
        code = 503
    else:
        if last is None:
            # Installation recente : aucun job n'a encore tourne (1er a 01h00).
            out['scheduler'] = 'no_run_yet'
        else:
            age_h = (datetime.now(timezone.utc).replace(tzinfo=None)
                     - last.run_at).total_seconds() / 3600
            out['last_job_hours_ago'] = round(age_h, 1)
            if age_h > 26:
                out['scheduler'] = 'stale'
                code = 503
    out['status'] = 'ok' if code == 200 else 'error'
    return jsonify(out), code


@bp.route('/rapport.pdf')
@login_required
def report_pdf():
    from flask import Response
    from app.pdf_report import build_pdf
    data = build_pdf(current_user)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d')
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="sentinelle-bilan-{stamp}.pdf"'})


@bp.route('/tendances')
@login_required
def trends():
    from sqlalchemy import func
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    labels = [d.strftime('%d/%m') for d in days]

    # Series sur 30 jours : une requete groupee par serie (et non une par jour).
    backups = {'ok': [], 'warning': [], 'failed': []}
    show_backups = current_user.can_view('backups')
    if show_backups:
        eff_status = func.coalesce(BackupCheck.first_status, BackupCheck.status)
        rows = db.session.query(BackupCheck.check_date, eff_status, func.count()) \
            .filter(BackupCheck.check_date >= days[0]) \
            .group_by(BackupCheck.check_date, eff_status).all()
        per_day = {}
        for d, st, n in rows:
            per_day.setdefault(d, {})[st] = n
        for d in days:
            counts = per_day.get(d, {})
            backups['ok'].append(counts.get('ok', 0))
            backups['warning'].append(counts.get('warning', 0))
            backups['failed'].append(counts.get('failed', 0))

    alerts = []
    show_alerts = current_user.can_view('alerts')
    if show_alerts:
        sent_day = func.date(AlertLog.sent_at)
        rows = db.session.query(sent_day, func.count()) \
            .filter(AlertLog.status == 'sent', sent_day >= days[0].isoformat()) \
            .group_by(sent_day).all()
        per_day = {str(d): n for d, n in rows}
        alerts = [per_day.get(d.isoformat(), 0) for d in days]

    # Repartition globale par statut (categories visibles)
    sources = [
        ('accounts', Account, lambda o: o.status()),
        ('certificates', Certificate, lambda o: o.status()),
        ('domains', Domain, lambda o: o.status()),
        ('backups', Backup, lambda o: o.computed_status()),
        ('tests', TestTask, lambda o: o.computed_status()),
        ('reviews', AccessReview, lambda o: o.computed_status()),
        ('updates', SystemUpdate, lambda o: o.status_color()),
    ]
    dist = {'danger': 0, 'warning': 0, 'info': 0, 'success': 0}
    for cat, model, statusf in sources:
        if not current_user.can_view(cat):
            continue
        for o in model.query.filter_by(is_active=True).all():
            s = statusf(o)
            if s in dist:
                dist[s] += 1

    return render_template('trends.html', labels=labels, backups=backups,
                           alerts=alerts, dist=dist,
                           show_backups=show_backups, show_alerts=show_alerts)


@bp.route('/etat/<status>')
@login_required
def by_status(status):
    labels = {'danger': 'Critiques', 'warning': 'À surveiller',
              'info': 'Proches', 'success': 'OK'}
    if status not in labels:
        abort(404)
    sources = [
        ('accounts', 'Comptes', Account, lambda o: f'{o.service_name} ({o.username})', 'accounts', lambda o: o.status()),
        ('certificates', 'Certificats', Certificate, lambda o: f'{o.service_name} - {o.domain}', 'certificates', lambda o: o.status()),
        ('domains', 'Domaines', Domain, lambda o: o.name, 'domains', lambda o: o.status()),
        ('backups', 'Backups', Backup, lambda o: o.service_name, 'backups', lambda o: o.computed_status()),
        ('tests', 'Tests', TestTask, lambda o: o.name, 'tests', lambda o: o.computed_status()),
        ('reviews', 'Revue de droits', AccessReview, lambda o: o.application, 'reviews', lambda o: o.computed_status()),
        ('updates', 'Mises à jour', SystemUpdate, lambda o: o.name, 'updates', lambda o: o.status_color()),
        ('inventory', 'Inventaire', Equipment, lambda o: o.name, 'inventory', lambda o: o.computed_status()),
    ]
    items = []
    for cat, label, model, namef, prefix, statusf in sources:
        if not current_user.can_view(cat):
            continue
        for o in model.query.filter_by(is_active=True).all():
            if statusf(o) == status:
                items.append({'cat': label, 'name': namef(o), 'url': f'/{prefix}/{o.id}'})
    items.sort(key=lambda x: x['cat'])
    return render_template('by_status.html', status=status, label=labels[status], items=items)


@bp.route('/trash')
@login_required
def trash():
    from app.trash import list_trashed
    return render_template('trash.html', groups=list_trashed(current_user))


@bp.route('/trash/restore', methods=['POST'])
@login_required
def trash_restore():
    from app.trash import restore
    from app.audit import record
    res = restore(current_user, request.form.get('entity_type', ''),
                  request.form.get('entity_id', '0'), current_user.username)
    if res:
        record('restauration', detail=f'{res[0]} : {res[1]}', category='corbeille')
    flash('Élément restauré.' if res else 'Restauration impossible.',
          'success' if res else 'danger')
    return redirect(url_for('dashboard.trash'))


@bp.route('/trash/purge-one', methods=['POST'])
@login_required
def trash_purge_one():
    # Pas de @require_delete : il deduit la categorie du blueprint (ici
    # « dashboard », donc aucune). Le droit can_delete(<categorie de
    # l'element>) est verifie dans trash.purge_one().
    from app.trash import purge_one
    from app.audit import record
    res = purge_one(current_user, request.form.get('entity_type', ''),
                    request.form.get('entity_id', '0'))
    if res:
        record('suppression definitive', detail=f'{res[0]} : {res[1]}', category='corbeille')
    flash('Élément supprimé définitivement.' if res else 'Suppression impossible.',
          'success' if res else 'danger')
    return redirect(url_for('dashboard.trash'))


@bp.route('/trash/purge', methods=['POST'])
@login_required
def trash_purge():
    # Droits verifies categorie par categorie dans trash.purge_all().
    from app.trash import purge_all
    from app.audit import record
    n = purge_all(current_user)
    if n:
        record('corbeille videe', detail=f'{n} element(s) supprime(s)', category='corbeille')
    flash(f'Corbeille vidée ({n} élément(s) supprimé(s) définitivement).'
          if n else 'Rien à supprimer.', 'success' if n else 'info')
    return redirect(url_for('dashboard.trash'))


def _agenda_items(user):
    """Echeances (rotations MDP, certificats, domaines, tests, revues) triees
    par date et filtrees selon les droits de `user`. Partage entre la page
    Agenda et le flux ICS (ou `user` peut venir d'un jeton, sans session)."""
    today = datetime.now(timezone.utc).date()
    items = []

    def add(cat, icon, name, date, detail, url):
        if not date:
            return
        items.append({'cat': cat, 'icon': icon, 'name': name, 'date': date,
                      'days': (date - today).days, 'detail': detail, 'url': url})

    if user.can_view('accounts'):
        for a in Account.query.filter_by(is_active=True).all():
            add('Comptes', 'key', f'{a.service_name} ({a.username})',
                a.next_password_change, 'Rotation du mot de passe', f'/accounts/{a.id}')
    if user.can_view('certificates'):
        for c in Certificate.query.filter_by(is_active=True).all():
            add('Certificats', 'award', f'{c.service_name} - {c.domain}',
                c.expiry_date, 'Expiration du certificat', f'/certificates/{c.id}')
    if user.can_view('domains'):
        for d in Domain.query.filter_by(is_active=True).all():
            add('Domaines', 'globe', d.name, d.expiry_date,
                'Expiration du domaine', f'/domains/{d.id}')
    if user.can_view('tests'):
        for t in TestTask.query.filter_by(is_active=True).all():
            add('Tests', 'clipboard-check', t.name, t.next_due,
                'Test a effectuer', f'/tests/{t.id}')
    if user.can_view('reviews'):
        for r in AccessReview.query.filter_by(is_active=True).all():
            add('Revue de droits', 'person-check', r.application, r.next_review,
                'Revue des acces', f'/reviews/{r.id}')
    if user.can_view('contracts'):
        for c in Contract.query.filter_by(is_active=True).all():
            add('Contrats', 'file-earmark-text', c.name, c.action_deadline(),
                'Échéance / préavis du contrat', f'/contracts/{c.id}')
    # Inventaire : echeances budgetaires anticipees (garantie materielle, fin de
    # support de l'OS), utiles a un DSI bien avant l'echeance.
    if user.can_view('inventory'):
        for e in Equipment.query.filter_by(is_active=True).all():
            add('Inventaire', 'hdd-stack', f'{e.name} (garantie)', e.warranty_end,
                'Fin de garantie matérielle', f'/inventory/{e.id}')
            ei = e.eol_info()
            if ei and ei.get('eol_date'):
                add('Inventaire', 'hdd-stack', f'{e.name} (fin de support OS)',
                    ei['eol_date'], 'Fin de support de l\'OS', f'/inventory/{e.id}')

    items.sort(key=lambda x: x['date'])
    return today, items


@bp.route('/agenda.ics')
def agenda_ics():
    """Flux iCalendar des echeances, pour Outlook/Thunderbird.

    Deux modes d'acces :
      - utilisateur connecte (telechargement ponctuel depuis la page Agenda) ;
      - ?token=<jeton personnel> : abonnement calendrier, sans session — le
        client recupere le flux periodiquement et reste a jour tout seul.
    Le flux est filtre selon les droits de l'utilisateur proprietaire du jeton."""
    from flask import Response, current_app, abort
    from app.models import User
    token = (request.args.get('token') or '').strip()
    if token:
        user = User.query.filter_by(ics_token=token).first()
        if user is None:
            abort(403)
    elif current_user.is_authenticated:
        user = current_user
    else:
        return current_app.login_manager.unauthorized()

    _, items = _agenda_items(user)
    base = current_app.config.get('APP_BASE_URL', '').rstrip('/')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    def esc(text):
        return (str(text).replace('\\', '\\\\').replace(';', '\\;')
                .replace(',', '\\,').replace('\n', '\\n'))

    def fold(line):
        # RFC 5545 : lignes longues repliees (continuation = espace en tete).
        out = []
        while len(line) > 70:
            out.append(line[:70])
            line = ' ' + line[70:]
        out.append(line)
        return out

    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//Sentinelle//Agenda//FR', 'CALSCALE:GREGORIAN',
             'X-WR-CALNAME:Sentinelle - Échéances',
             # Suggestion de cadence de rafraichissement pour les clients abonnes.
             'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H']
    for it in items:
        uid = 'sentinelle-' + it['url'].strip('/').replace('/', '-') + '@sentinelle'
        ev = ['BEGIN:VEVENT',
              f'UID:{uid}',
              f'DTSTAMP:{stamp}',
              f"DTSTART;VALUE=DATE:{it['date'].strftime('%Y%m%d')}",
              f"SUMMARY:{esc('[' + it['cat'] + '] ' + it['name'])}",
              f"DESCRIPTION:{esc(it['detail'])}"]
        if base:
            ev.append(f"URL:{base}{it['url']}")
        ev.append('END:VEVENT')
        for line in ev:
            lines.extend(fold(line))
    lines.append('END:VCALENDAR')
    body = '\r\n'.join(lines) + '\r\n'
    headers = {'Cache-Control': 'no-cache'}
    if not token:
        # Telechargement manuel : proposer un fichier. En abonnement, les
        # clients calendrier consomment le flux directement.
        headers['Content-Disposition'] = 'attachment; filename="sentinelle-agenda.ics"'
    return Response(body, mimetype='text/calendar', headers=headers)


@bp.route('/agenda/ics-token', methods=['POST'])
@login_required
def agenda_ics_token():
    """Genere, regenere ou desactive le jeton d'abonnement ICS de l'utilisateur.
    Regenerer invalide l'ancien lien (les abonnements existants cessent)."""
    import secrets
    if request.form.get('action') == 'disable':
        current_user.ics_token = None
        flash("Lien d'abonnement désactivé : les calendriers abonnés ne seront plus alimentés.", 'success')
    else:
        regen = current_user.ics_token is not None
        current_user.ics_token = secrets.token_urlsafe(32)
        flash("Nouveau lien d'abonnement généré." +
              (" L'ancien lien ne fonctionne plus." if regen else ''), 'success')
    db.session.commit()
    return redirect(url_for('dashboard.agenda'))


@bp.route('/agenda')
@login_required
def agenda():
    """Echeances a venir (rotations MDP, certificats, domaines, tests),
    regroupees par horizon et filtrees selon les droits de l'utilisateur."""
    from flask import current_app
    today, items = _agenda_items(current_user)
    base = current_app.config.get('APP_BASE_URL', '').rstrip('/')
    ics_url = (f"{base}{url_for('dashboard.agenda_ics')}?token={current_user.ics_token}"
               if current_user.ics_token else None)
    # Couleur par horizon : seul le retard est « danger » ; l'echeance proche
    # est « warning » (eviter deux paliers rouges consecutifs / la sur-alerte).
    buckets = [
        ('En retard', [i for i in items if i['days'] < 0], 'danger'),
        ('Cette semaine', [i for i in items if 0 <= i['days'] <= 7], 'warning'),
        ('Ce mois-ci', [i for i in items if 7 < i['days'] <= 31], 'warning'),
        ('Dans les 90 jours', [i for i in items if 31 < i['days'] <= 90], 'info'),
    ]
    buckets = [(label, lst, color) for label, lst, color in buckets if lst]
    return render_template('agenda.html', buckets=buckets, today=today, ics_url=ics_url)


@bp.route('/')
@login_required
def index():
    today = datetime.now(timezone.utc).date()

    # On ne charge que les categories que l'utilisateur a le droit de voir,
    # afin que stats, urgences et tableau des backups n'exposent rien d'interdit.
    accounts = Account.query.filter_by(is_active=True).all() if current_user.can_view('accounts') else []
    certificates = Certificate.query.filter_by(is_active=True).all() if current_user.can_view('certificates') else []
    domains = Domain.query.filter_by(is_active=True).all() if current_user.can_view('domains') else []
    backups = Backup.query.filter_by(is_active=True).all() if current_user.can_view('backups') else []
    tests = TestTask.query.filter_by(is_active=True).all() if current_user.can_view('tests') else []
    reviews = AccessReview.query.filter_by(is_active=True).all() if current_user.can_view('reviews') else []
    updates = SystemUpdate.query.filter_by(is_active=True).all() if current_user.can_view('updates') else []
    equipments = Equipment.query.filter_by(is_active=True).all() if current_user.can_view('inventory') else []
    contracts = Contract.query.filter_by(is_active=True).all() if current_user.can_view('contracts') else []

    # Statut calcule UNE seule fois par objet (computed_status() requete la
    # base pour les backups et l'inventaire), puis reutilise pour les stats,
    # les urgences et la conformite.
    acc_st = [(a, a.status()) for a in accounts]
    cert_st = [(c, c.status()) for c in certificates]
    dom_st = [(d, d.status()) for d in domains]
    bkp_st = [(b, b.computed_status()) for b in backups]
    tst_st = [(t, t.computed_status()) for t in tests]
    rev_st = [(r, r.computed_status()) for r in reviews]
    upd_st = [(u, u.status_color()) for u in updates]
    inv_st = [(e, e.computed_status()) for e in equipments]
    ctr_st = [(c, c.status()) for c in contracts]

    def _counts(pairs):
        return {'total': len(pairs),
                'danger': sum(1 for _, s in pairs if s == 'danger'),
                'warning': sum(1 for _, s in pairs if s == 'warning'),
                'ok': sum(1 for _, s in pairs if s == 'success')}

    urgent_items = []
    for a, st in acc_st:
        if st == 'danger':
            if a.next_password_change:
                days = (a.next_password_change - today).days
                detail = (f'MDP a changer depuis {abs(days)} jour(s)' if days < 0
                          else f'MDP a changer dans {days} jour(s)')
            else:
                detail = 'Date de rotation non definie'
            urgent_items.append({
                'type': 'account', 'name': f'{a.service_name} ({a.username})',
                'detail': detail,
                'status': 'danger', 'url': f'/accounts/{a.id}'
            })
    for c, st in cert_st:
        if st in ('danger', 'warning'):
            days = (c.expiry_date - today).days
            urgent_items.append({
                'type': 'certificate', 'name': f'{c.service_name} - {c.domain}',
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': st, 'url': f'/certificates/{c.id}'
            })
    for d, st in dom_st:
        if st in ('danger', 'warning') and d.expiry_date:
            days = (d.expiry_date - today).days
            urgent_items.append({
                'type': 'domain', 'name': d.name,
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': st, 'url': f'/domains/{d.id}'
            })
    for b, st in bkp_st:
        if st == 'danger':
            tc = b.today_check()
            detail = 'Non verifie' if not tc else f'Check: {tc.status}'
            urgent_items.append({
                'type': 'backup', 'name': b.service_name,
                'detail': detail,
                'status': 'danger', 'url': f'/backups/{b.id}'
            })
    for t, st in tst_st:
        if st == 'danger':
            if t.next_due:
                days = (t.next_due - today).days
                detail = (f'Test en retard de {abs(days)} jour(s)' if days < 0
                          else f'Test a faire dans {days} jour(s)')
            else:
                detail = 'Echeance non planifiee'
            urgent_items.append({
                'type': 'test', 'name': t.name,
                'detail': detail,
                'status': 'danger', 'url': f'/tests/{t.id}'
            })
    for r, st in rev_st:
        if st in ('danger', 'warning'):
            days = (r.next_review - today).days if r.next_review else None
            detail = (f'Revue dans {days} j' if days is not None and days >= 0
                      else (f'Revue en retard de {abs(days)} j' if days is not None else 'Revue a planifier'))
            urgent_items.append({
                'type': 'review', 'name': r.application, 'detail': detail,
                'status': st, 'url': f'/reviews/{r.id}'
            })
    for u, st in upd_st:
        if st in ('danger', 'warning'):
            detail = 'Mise a jour critique' if u.status == 'critical' else 'Mise a jour disponible'
            urgent_items.append({
                'type': 'update', 'name': u.name, 'detail': detail,
                'status': st, 'url': f'/updates/{u.id}'
            })

    for c, st in ctr_st:
        if st in ('danger', 'warning'):
            deadline = c.action_deadline()
            days = (deadline - today).days if deadline else None
            detail = (f'Agir avant {days} jour(s)' if days is not None and days >= 0
                      else (f'Date limite depassee de {abs(days)} jour(s)' if days is not None
                            else 'Echeance a renseigner'))
            urgent_items.append({
                'type': 'contract', 'name': c.name, 'detail': detail,
                'status': st, 'url': f'/contracts/{c.id}'
            })

    urgent_items.sort(key=lambda x: {'danger': 0, 'warning': 1, 'info': 2}.get(x['status'], 3))

    recent_alerts = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(10).all()

    # Widget « À venir » : prochaines échéances (0 à 60 jours), toutes catégories
    upcoming = []

    def _add_up(date_val, label, icon, url):
        if date_val:
            dleft = (date_val - today).days
            if 0 <= dleft <= 60:
                upcoming.append({'days': dleft, 'label': label, 'icon': icon, 'url': url})

    for a in accounts:
        _add_up(a.next_password_change, a.service_name, 'bi-key', f'/accounts/{a.id}')
    for c in certificates:
        _add_up(c.expiry_date, c.service_name, 'bi-award', f'/certificates/{c.id}')
    for d in domains:
        _add_up(d.expiry_date, d.name, 'bi-globe', f'/domains/{d.id}')
    for t in tests:
        _add_up(t.next_due, t.name, 'bi-clipboard-check', f'/tests/{t.id}')
    for r in reviews:
        _add_up(r.next_review, r.application, 'bi-person-check', f'/reviews/{r.id}')
    for e in equipments:
        _add_up(e.warranty_end, f'{e.name} (garantie)', 'bi-hdd-stack', f'/inventory/{e.id}')
    for c in contracts:
        _add_up(c.action_deadline(), f'{c.name} (contrat)', 'bi-file-earmark-text', f'/contracts/{c.id}')
    upcoming.sort(key=lambda x: x['days'])
    upcoming = upcoming[:7]

    # Check du jour reutilise depuis computed_status() (memoise sur l'instance) :
    # evite une requete redondante par backup, et garde un seul critere de date
    # faisant foi (today_check()).
    backup_checks = {b.id: b.today_check() for b in backups}

    stats = {
        'accounts': _counts(acc_st),
        'certificates': _counts(cert_st),
        'domains': _counts(dom_st),
        'backups': _counts(bkp_st),
        'tests': _counts(tst_st),
        'reviews': _counts(rev_st),
        'updates': _counts(upd_st),
        'inventory': _counts(inv_st),
        'contracts': _counts(ctr_st),
    }

    # La conformite globale n'agrege que les categories selectionnees en config
    # (toutes par defaut ; l'admin ajuste dans Administration > Parametres).
    from app.app_settings import get_conformity_categories
    included = set(get_conformity_categories())
    totals = {'total': 0, 'ok': 0, 'warning': 0, 'danger': 0}
    for cat, v in stats.items():
        if cat not in included:
            continue
        for k in totals:
            totals[k] += v[k]
    conformity = round(100 * totals['ok'] / totals['total']) if totals['total'] else 100

    # Disposition personnalisable : liste des blocs pertinents pour cet
    # utilisateur (selon droits/donnees), puis resolution ordre/visibilite.
    from flask import current_app
    widget_meta = {w['key']: w for w in DASHBOARD_WIDGETS}
    available = []
    for w in DASHBOARD_WIDGETS:
        key = w['key']
        if key == 'conformity' and not totals['total']:
            continue
        if key == 'backups_today' and not (backups and current_user.can_view('backups')):
            continue
        if key == 'alerts' and not current_user.can_view('alerts'):
            continue
        available.append(key)

    # Vignettes de synthese : disponibles selon les droits, dans l'ordre choisi.
    card_meta = {c['key']: c for c in STAT_CARDS}
    available_cards = [c['key'] for c in STAT_CARDS if current_user.can_view(c['cat'])]

    dashboard_custom = bool(current_app.config.get('DASHBOARD_CUSTOM', True))
    if dashboard_custom:
        dash_visible, dash_hidden = resolve_dashboard_layout(current_user, available)
        dash_spans = resolve_widget_spans(current_user)
        card_order = resolve_card_order(current_user, available_cards)
    else:
        dash_visible, dash_hidden = available, []
        dash_spans = dict(WIDGET_SPAN_DEFAULT)
        card_order = available_cards

    dash_cards = [dict(card_meta[k], url=url_for(card_meta[k]['endpoint']),
                       s=stats[k]) for k in card_order]

    return render_template('dashboard.html', stats=stats, urgent_items=urgent_items,
                           recent_alerts=recent_alerts, backups=backups,
                           backup_checks=backup_checks, today=today,
                           totals=totals, conformity=conformity, upcoming=upcoming,
                           dashboard_custom=dashboard_custom, widget_meta=widget_meta,
                           dash_visible=dash_visible, dash_hidden=dash_hidden,
                           dash_spans=dash_spans, dash_cards=dash_cards)


@bp.route('/dashboard/layout', methods=['POST'])
@login_required
def save_layout():
    """Enregistre la disposition personnalisee du tableau de bord de l'utilisateur
    courant (ordre + blocs masques). AJAX : renvoie du JSON, sans rechargement.

    Pas de @require_edit : n'ecrit que les preferences d'affichage de l'utilisateur
    lui-meme (aucune donnee metier), a l'image de agenda_ics_token."""
    import json
    from flask import jsonify, current_app
    if not current_app.config.get('DASHBOARD_CUSTOM', True):
        return jsonify(ok=False, error='disabled'), 403
    data = request.get_json(silent=True) or {}
    if data.get('reset'):
        current_user.dashboard_prefs = None
        db.session.commit()
        return jsonify(ok=True)
    valid = {w['key'] for w in DASHBOARD_WIDGETS}
    order = [k for k in (data.get('order') or []) if k in valid]
    hidden = [k for k in (data.get('hidden') or []) if k in valid]
    spans = {}
    raw_spans = data.get('spans')
    for key, val in (raw_spans if isinstance(raw_spans, dict) else {}).items():
        if key not in valid:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if WIDGET_SPAN_MIN <= n <= WIDGET_SPAN_MAX:
            spans[key] = n
    # Ordre des vignettes de synthese. Absent du payload -> on preserve l'existant.
    valid_cards = {c['key'] for c in STAT_CARDS}
    raw_cards = data.get('cards')
    if isinstance(raw_cards, list):
        cards = [k for k in raw_cards if k in valid_cards]
    else:
        cards = [k for k in _load_prefs(current_user).get('cards', []) if k in valid_cards]
    current_user.dashboard_prefs = json.dumps(
        {'order': order, 'hidden': hidden, 'spans': spans, 'cards': cards})
    db.session.commit()
    return jsonify(ok=True)


@bp.route('/quick-check', methods=['POST'])
@login_required
def quick_check():
    if not current_user.can_edit('backups'):
        flash("Vous n'avez pas les droits pour valider un backup.", 'danger')
        return redirect(url_for('dashboard.index'))
    backup_id = request.form.get('backup_id')
    status = request.form.get('status', 'ok')
    comment = request.form.get('comment', '')
    today = datetime.now(timezone.utc).date()

    from app.backups import record_backup_check
    record_backup_check(backup_id, today, status, comment, current_user.username)
    db.session.commit()
    flash('Backup valide', 'success')
    return redirect(url_for('dashboard.index'))
