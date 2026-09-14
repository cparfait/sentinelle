import hmac
from datetime import datetime, timedelta, timezone
from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   jsonify, current_app)
from flask_login import login_required, current_user
from app import db, csrf
from app.models import Backup, BackupCheck, BackupHistory
from app.inventory import active_equipments as _active_equipments
from app.inventory import parse_equipment_id as _parse_equipment_id
from app.forms_util import status_rank

from app.decorators import require_edit, require_delete, view_guard
bp = Blueprint('backups', __name__)


@bp.before_request
def _guard_view():
    # La route d'ingestion (machine, sans session) n'est pas concernee :
    # view_guard ne bloque que les utilisateurs CONNECTES sans droit de lecture.
    if request.endpoint == 'backups.ingest':
        return None
    return view_guard('backups')


@bp.route('/ingest', methods=['POST'])
@csrf.exempt
def ingest():
    """Point d'entree machine-to-machine : recoit le mail recap de backup
    (transfere par une regle/flux) et enregistre les checks du jour.
    Securise par un jeton (BACKUP_INGEST_TOKEN), pas de session utilisateur."""
    token = current_app.config.get('BACKUP_INGEST_TOKEN')
    if not token:
        return jsonify(ok=False, error="Ingestion desactivee (BACKUP_INGEST_TOKEN non defini)."), 503
    provided = request.headers.get('X-Sentinelle-Token') or request.args.get('token', '')
    # Comparaison a temps constant : ne fuit pas la longueur/le prefixe du jeton.
    if not hmac.compare_digest(provided, token):
        return jsonify(ok=False, error="Jeton invalide."), 403

    if request.is_json:
        data = request.get_json(silent=True) or {}
        subject = data.get('subject', '')
        body = data.get('body', '')
    else:
        subject = request.args.get('subject', '')
        body = request.get_data(as_text=True) or ''

    from app.backup_ingest import parse_and_record
    results = parse_and_record(subject, body)
    return jsonify(ok=True, updated=results, count=len(results))


@bp.route('/scan-inbox', methods=['POST'])
@login_required
@require_edit
def scan_inbox_now():
    directory = current_app.config.get('BACKUP_INBOX_DIR')
    if not directory:
        flash("Aucun repertoire de mails configure (BACKUP_INBOX_DIR).", 'danger')
        return redirect(url_for('backups.list'))
    from app.backup_ingest import scan_inbox
    summary = scan_inbox(directory)
    if summary.get('error'):
        flash(summary['error'], 'danger')
    else:
        n_files = len(summary['files'])
        n_updates = sum(len(f.get('updated', [])) for f in summary['files'])
        flash(f"{n_files} fichier(s) traite(s), {n_updates} sauvegarde(s) mise(s) a jour.",
              'success' if n_files else 'info')
    return redirect(url_for('backups.list'))


@bp.route('/')
@login_required
def list():
    backups = Backup.query.filter_by(is_active=True).all()
    q = request.args.get('q', '').strip()
    from app.paging import paginate, text_search
    backups = text_search(backups, q, ['service_name', 'location', 'backup_type', 'description'])
    backups.sort(key=lambda b: status_rank(b.computed_status()))
    backups, page, pages, total = paginate(backups)
    today = datetime.now(timezone.utc).date()
    today_checks = {}
    for b in backups:
        today_checks[b.id] = b.today_check()
    return render_template('backups/list.html', backups=backups, today_checks=today_checks,
                           today=today, q=q, page=page, pages=pages, total=total)


_STATUS_LABELS = {'ok': 'OK', 'warning': 'Warning', 'failed': 'Échec'}


def record_backup_check(backup_id, check_date, status, comment, user):
    """Cree ou met a jour le check d'un jour et trace l'action dans l'historique.
    Le premier etat du jour (first_status) est fige a la creation."""
    # Garde-fou : un statut hors liste blanche fausserait les stats -> repli 'ok'.
    if status not in _STATUS_LABELS:
        status = 'ok'
    label = _STATUS_LABELS.get(status, status)
    existing = BackupCheck.query.filter_by(backup_id=backup_id, check_date=check_date).first()
    if existing:
        old = existing.status
        existing.status = status
        if comment:
            existing.comment = comment
        existing.checked_by = user
        if existing.first_status is None:
            existing.first_status = old  # retro-compat : fige l'etat connu
        if old != status:
            note = (f"Statut du {check_date.strftime('%d/%m/%Y')} modifié : "
                    f"{_STATUS_LABELS.get(old, old)} → {label}")
        else:
            note = f"Re-validation du {check_date.strftime('%d/%m/%Y')} : {label}"
    else:
        existing = BackupCheck(backup_id=backup_id, check_date=check_date, status=status,
                               first_status=status, comment=comment or None, checked_by=user)
        db.session.add(existing)
        note = f"Check du {check_date.strftime('%d/%m/%Y')} : {label}"
    if comment:
        note += f" — {comment}"
    db.session.add(BackupHistory(backup_id=backup_id, action='check', status=status,
                                 comment=note, performed_by=user))
    return existing


@bp.route('/daily', methods=['GET', 'POST'])
@login_required
@require_edit
def daily():
    backups = Backup.query.filter_by(is_active=True).order_by(Backup.service_name).all()
    today = datetime.now(timezone.utc).date()

    if request.method == 'POST':
        for b in backups:
            status = request.form.get(f'status_{b.id}')
            comment = request.form.get(f'comment_{b.id}', '')
            if status:
                record_backup_check(b.id, today, status, comment, current_user.username)
        db.session.commit()
        flash('Checks quotidiens enregistres', 'success')
        return redirect(url_for('backups.daily'))

    # Checks du jour charges en une seule requete (evite un N+1 par backup).
    rows = {c.backup_id: c for c in BackupCheck.query.filter_by(check_date=today).all()}
    checks = {b.id: rows.get(b.id) for b in backups}

    return render_template('backups/daily.html', backups=backups, checks=checks, today=today)


@bp.route('/stats')
@login_required
def stats():
    from collections import defaultdict
    backups = Backup.query.filter_by(is_active=True).all()
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=29)
    stats_data = []

    # Pre-chargement groupe (evite un N+1 : 30 requetes/jour + 1 par backup).
    # - calendrier 30 jours : checks de la fenetre, indexes par (backup, jour) ;
    # - totaux : tous les checks, regroupes par backup.
    recent = defaultdict(dict)
    for c in BackupCheck.query.filter(BackupCheck.check_date >= window_start).all():
        recent[c.backup_id][c.check_date] = c
    all_by_backup = defaultdict(list)
    for c in BackupCheck.query.all():
        all_by_backup[c.backup_id].append(c)

    def _fs(c):
        return c.first_status or c.status

    for b in backups:
        rate_30 = b.success_rate(30)
        rate_7 = b.success_rate(7)
        streak = b.streak()

        last_30 = []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            c = recent[b.id].get(d)
            day_status = (c.first_status or c.status) if c else None
            recovered = bool(c and c.first_status and c.first_status != c.status and c.status == 'ok')
            last_30.append({
                'date': d.strftime('%Y-%m-%d'),
                'date_display': d.strftime('%d/%m'),
                'status': day_status,           # premier etat du jour (incident visible)
                'recovered': recovered,         # repasse OK apres incident
                'comment': c.comment if c else None
            })

        # Totaux bases sur le premier etat de chaque jour
        all_checks = all_by_backup[b.id]
        total_ok = sum(1 for c in all_checks if _fs(c) == 'ok')
        total_failed = sum(1 for c in all_checks if _fs(c) == 'failed')
        total_warning = sum(1 for c in all_checks if _fs(c) == 'warning')

        stats_data.append({
            'backup': b,
            'rate_30': rate_30,
            'rate_7': rate_7,
            'streak': streak,
            'total_ok': total_ok,
            'total_failed': total_failed,
            'total_warning': total_warning,
            'calendar': last_30
        })

    global_ok = sum(s['total_ok'] for s in stats_data)
    global_failed = sum(s['total_failed'] for s in stats_data)
    global_warning = sum(s['total_warning'] for s in stats_data)
    global_total = global_ok + global_failed + global_warning

    return render_template('backups/stats.html', stats_data=stats_data,
                           global_ok=global_ok, global_failed=global_failed,
                           global_warning=global_warning, global_total=global_total,
                           today=today)


@bp.route('/<int:id>')
@login_required
def detail(id):
    backup = Backup.query.get_or_404(id)
    checks = backup.checks.order_by(BackupCheck.check_date.desc()).limit(60).all()
    # Toutes les saisies de statut (plusieurs possibles le meme jour), du plus
    # recent au plus ancien : c'est l'historique detaille affiche dans la page.
    check_events = (BackupHistory.query
                    .filter_by(backup_id=id, action='check')
                    .order_by(BackupHistory.performed_at.desc())
                    .limit(200).all())
    histories = BackupHistory.query.filter_by(backup_id=id).order_by(BackupHistory.performed_at.desc()).all()
    return render_template('backups/detail.html', backup=backup, checks=checks,
                           check_events=check_events, histories=histories)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        service_name = (request.form.get('service_name') or '').strip()
        if not service_name:
            flash('Le nom du service est obligatoire.', 'danger')
            return render_template('backups/form.html', backup=None,
                                   equipments=_active_equipments())
        b = Backup(
            service_name=service_name,
            backup_type=request.form.get('backup_type'),
            location=request.form.get('location'),
            frequency=request.form.get('frequency'),
            expected_time=request.form.get('expected_time'),
            description=request.form.get('description'),
            priority=request.form.get('priority', 'medium'),
            equipment_id=_parse_equipment_id(request.form.get('equipment_id')),
        )
        db.session.add(b)
        db.session.commit()

        h = BackupHistory(
            backup_id=b.id, action='creation',
            comment=f'Backup cree : {b.service_name}', performed_by=current_user.username
        )
        db.session.add(h)
        db.session.commit()
        flash('Backup ajoute avec succes', 'success')
        return redirect(url_for('backups.list'))
    return render_template('backups/form.html', backup=None,
                           equipments=_active_equipments())


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    backup = Backup.query.get_or_404(id)
    if request.method == 'POST':
        service_name = (request.form.get('service_name') or '').strip()
        if not service_name:
            flash('Le nom du service est obligatoire.', 'danger')
            return render_template('backups/form.html', backup=backup,
                                   equipments=_active_equipments())
        backup.service_name = service_name
        backup.backup_type = request.form.get('backup_type')
        backup.location = request.form.get('location')
        backup.frequency = request.form.get('frequency')
        backup.expected_time = request.form.get('expected_time')
        backup.description = request.form.get('description')
        backup.priority = request.form.get('priority', 'medium')
        backup.equipment_id = _parse_equipment_id(request.form.get('equipment_id'))
        db.session.commit()
        flash('Backup modifie avec succes', 'success')
        return redirect(url_for('backups.detail', id=id))
    return render_template('backups/form.html', backup=backup,
                           equipments=_active_equipments())


@bp.route('/<int:id>/check', methods=['POST'])
@login_required
@require_edit
def check(id):
    Backup.query.get_or_404(id)  # garde 404, l'objet n'est pas utilise ensuite
    today = datetime.now(timezone.utc).date()
    status = request.form.get('status', 'ok')
    comment = request.form.get('comment', '')
    check_date_str = request.form.get('check_date')
    check_date = None
    if check_date_str:
        try:
            check_date = datetime.strptime(check_date_str, '%Y-%m-%d').date()
        except ValueError:
            check_date = today
    else:
        check_date = today

    record_backup_check(id, check_date, status, comment, current_user.username)
    db.session.commit()
    flash('Check enregistre', 'success')
    return redirect(url_for('backups.detail', id=id))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    backup = Backup.query.get_or_404(id)
    backup.is_active = False
    h = BackupHistory(
        backup_id=backup.id, action='deleted',
        comment=f'Backup desactive : {backup.service_name}', performed_by=current_user.username
    )
    db.session.add(h)
    db.session.commit()
    flash('Backup supprime', 'success')
    return redirect(url_for('backups.list'))
