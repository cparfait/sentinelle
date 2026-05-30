from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.models import (Account, Certificate, Backup, BackupCheck, TestTask,
                        AlertLog, Domain, AccessReview, SystemUpdate)
from app.snooze import is_snoozed
from app import db

from app.decorators import require_edit
bp = Blueprint('dashboard', __name__)


@bp.route('/tendances')
@login_required
def trends():
    from sqlalchemy import func
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    labels = [d.strftime('%d/%m') for d in days]

    backups = {'ok': [], 'warning': [], 'failed': []}
    show_backups = current_user.can_view('backups')
    if show_backups:
        for d in days:
            checks = BackupCheck.query.filter_by(check_date=d).all()
            backups['ok'].append(sum(1 for c in checks if c.status == 'ok'))
            backups['warning'].append(sum(1 for c in checks if c.status == 'warning'))
            backups['failed'].append(sum(1 for c in checks if c.status == 'failed'))

    alerts = []
    show_alerts = current_user.can_view('alerts')
    if show_alerts:
        for d in days:
            alerts.append(AlertLog.query.filter(
                func.date(AlertLog.sent_at) == d, AlertLog.status == 'sent').count())

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
    from app.trash import purge_all
    from app.audit import record
    n = purge_all(current_user)
    if n:
        record('corbeille videe', detail=f'{n} element(s) supprime(s)', category='corbeille')
    flash(f'Corbeille vidée ({n} élément(s) supprimé(s) définitivement).'
          if n else 'Rien à supprimer.', 'success' if n else 'info')
    return redirect(url_for('dashboard.trash'))


@bp.route('/agenda')
@login_required
def agenda():
    """Echeances a venir (rotations MDP, certificats, domaines, tests),
    regroupees par horizon et filtrees selon les droits de l'utilisateur."""
    today = datetime.now(timezone.utc).date()
    items = []

    def add(cat, icon, name, date, detail, url):
        if not date:
            return
        items.append({'cat': cat, 'icon': icon, 'name': name, 'date': date,
                      'days': (date - today).days, 'detail': detail, 'url': url})

    if current_user.can_view('accounts'):
        for a in Account.query.filter_by(is_active=True).all():
            add('Comptes', 'key', f'{a.service_name} ({a.username})',
                a.next_password_change, 'Rotation du mot de passe', f'/accounts/{a.id}')
    if current_user.can_view('certificates'):
        for c in Certificate.query.filter_by(is_active=True).all():
            add('Certificats', 'award', f'{c.service_name} - {c.domain}',
                c.expiry_date, 'Expiration du certificat', f'/certificates/{c.id}')
    if current_user.can_view('domains'):
        for d in Domain.query.filter_by(is_active=True).all():
            add('Domaines', 'globe', d.name, d.expiry_date,
                'Expiration du domaine', f'/domains/{d.id}')
    if current_user.can_view('tests'):
        for t in TestTask.query.filter_by(is_active=True).all():
            add('Tests', 'clipboard-check', t.name, t.next_due,
                'Test a effectuer', f'/tests/{t.id}')
    if current_user.can_view('reviews'):
        for r in AccessReview.query.filter_by(is_active=True).all():
            add('Revue de droits', 'person-check', r.application, r.next_review,
                'Revue des acces', f'/reviews/{r.id}')

    items.sort(key=lambda x: x['date'])
    buckets = [
        ('En retard', [i for i in items if i['days'] < 0], 'danger'),
        ('Cette semaine', [i for i in items if 0 <= i['days'] <= 7], 'danger'),
        ('Ce mois-ci', [i for i in items if 7 < i['days'] <= 31], 'warning'),
        ('Dans les 90 jours', [i for i in items if 31 < i['days'] <= 90], 'info'),
    ]
    buckets = [(label, lst, color) for label, lst, color in buckets if lst]
    return render_template('agenda.html', buckets=buckets, today=today)


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

    acc_danger = sum(1 for a in accounts if a.status() == 'danger')
    acc_warning = sum(1 for a in accounts if a.status() == 'warning')
    acc_ok = sum(1 for a in accounts if a.status() == 'success')

    cert_danger = sum(1 for c in certificates if c.status() == 'danger')
    cert_warning = sum(1 for c in certificates if c.status() == 'warning')
    cert_ok = sum(1 for c in certificates if c.status() == 'success')

    dom_danger = sum(1 for d in domains if d.status() == 'danger')
    dom_warning = sum(1 for d in domains if d.status() == 'warning')
    dom_ok = sum(1 for d in domains if d.status() == 'success')

    bkp_danger = sum(1 for b in backups if b.computed_status() == 'danger')
    bkp_warning = sum(1 for b in backups if b.computed_status() == 'warning')
    bkp_ok = sum(1 for b in backups if b.computed_status() == 'success')

    tst_danger = sum(1 for t in tests if t.computed_status() == 'danger')
    tst_warning = sum(1 for t in tests if t.computed_status() == 'warning')
    tst_ok = sum(1 for t in tests if t.computed_status() == 'success')

    rev_danger = sum(1 for r in reviews if r.computed_status() == 'danger')
    rev_warning = sum(1 for r in reviews if r.computed_status() == 'warning')
    rev_ok = sum(1 for r in reviews if r.computed_status() == 'success')

    upd_danger = sum(1 for u in updates if u.status_color() == 'danger')
    upd_warning = sum(1 for u in updates if u.status_color() == 'warning')
    upd_ok = sum(1 for u in updates if u.status_color() == 'success')

    urgent_items = []
    for a in accounts:
        if a.status() == 'danger':
            days = (a.next_password_change - today).days if a.next_password_change else 'N/A'
            urgent_items.append({
                'type': 'account', 'name': f'{a.service_name} ({a.username})',
                'detail': f'MDP a changer depuis {abs(days)} jour(s)' if isinstance(days, int) and days < 0 else f'MDP a changer dans {days} jour(s)',
                'status': 'danger', 'url': f'/accounts/{a.id}'
            })
    for c in certificates:
        if c.status() in ('danger', 'warning'):
            days = (c.expiry_date - today).days
            urgent_items.append({
                'type': 'certificate', 'name': f'{c.service_name} - {c.domain}',
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': c.status(), 'url': f'/certificates/{c.id}'
            })
    for d in domains:
        if d.status() in ('danger', 'warning') and d.expiry_date:
            days = (d.expiry_date - today).days
            urgent_items.append({
                'type': 'domain', 'name': d.name,
                'detail': f'Expire dans {days} jour(s)' if days >= 0 else f'Expire depuis {abs(days)} jour(s)',
                'status': d.status(), 'url': f'/domains/{d.id}'
            })
    for b in backups:
        if b.computed_status() == 'danger':
            tc = b.today_check()
            detail = 'Non verifie' if not tc else f'Check: {tc.status}'
            urgent_items.append({
                'type': 'backup', 'name': b.service_name,
                'detail': detail,
                'status': 'danger', 'url': f'/backups/{b.id}'
            })
    for t in tests:
        if t.computed_status() == 'danger':
            days = (t.next_due - today).days if t.next_due else 'N/A'
            urgent_items.append({
                'type': 'test', 'name': t.name,
                'detail': f'Test en retard de {abs(days)} jour(s)' if isinstance(days, int) and days < 0 else f'Test a faire dans {days} jour(s)',
                'status': 'danger', 'url': f'/tests/{t.id}'
            })
    for r in reviews:
        if r.computed_status() in ('danger', 'warning'):
            days = (r.next_review - today).days if r.next_review else None
            detail = (f'Revue dans {days} j' if days is not None and days >= 0
                      else (f'Revue en retard de {abs(days)} j' if days is not None else 'Revue a planifier'))
            urgent_items.append({
                'type': 'review', 'name': r.application, 'detail': detail,
                'status': r.computed_status(), 'url': f'/reviews/{r.id}'
            })
    for u in updates:
        if u.status_color() in ('danger', 'warning'):
            detail = 'Mise a jour critique' if u.status == 'critical' else 'Mise a jour disponible'
            urgent_items.append({
                'type': 'update', 'name': u.name, 'detail': detail,
                'status': u.status_color(), 'url': f'/updates/{u.id}'
            })

    urgent_items.sort(key=lambda x: {'danger': 0, 'warning': 1, 'info': 2}.get(x['status'], 3))

    recent_alerts = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(10).all()

    backup_checks = {}
    for b in backups:
        backup_checks[b.id] = BackupCheck.query.filter_by(
            backup_id=b.id, check_date=today
        ).first()

    stats = {
        'accounts': {'total': len(accounts), 'danger': acc_danger, 'warning': acc_warning, 'ok': acc_ok},
        'certificates': {'total': len(certificates), 'danger': cert_danger, 'warning': cert_warning, 'ok': cert_ok},
        'domains': {'total': len(domains), 'danger': dom_danger, 'warning': dom_warning, 'ok': dom_ok},
        'backups': {'total': len(backups), 'danger': bkp_danger, 'warning': bkp_warning, 'ok': bkp_ok},
        'tests': {'total': len(tests), 'danger': tst_danger, 'warning': tst_warning, 'ok': tst_ok},
        'reviews': {'total': len(reviews), 'danger': rev_danger, 'warning': rev_warning, 'ok': rev_ok},
        'updates': {'total': len(updates), 'danger': upd_danger, 'warning': upd_warning, 'ok': upd_ok},
    }

    totals = {'total': 0, 'ok': 0, 'warning': 0, 'danger': 0}
    for v in stats.values():
        for k in totals:
            totals[k] += v[k]
    conformity = round(100 * totals['ok'] / totals['total']) if totals['total'] else 100

    return render_template('dashboard.html', stats=stats, urgent_items=urgent_items,
                           recent_alerts=recent_alerts, backups=backups,
                           backup_checks=backup_checks, today=today,
                           totals=totals, conformity=conformity)


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

    existing = BackupCheck.query.filter_by(backup_id=backup_id, check_date=today).first()
    if existing:
        existing.status = status
        existing.comment = comment if comment else existing.comment
        existing.checked_by = current_user.username
    else:
        check = BackupCheck(
            backup_id=backup_id,
            check_date=today,
            status=status,
            comment=comment if comment else None,
            checked_by=current_user.username
        )
        db.session.add(check)
    db.session.commit()
    flash('Backup valide', 'success')
    return redirect(url_for('dashboard.index'))
