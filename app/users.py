from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import (User, Role, PERMISSION_CATEGORIES, CATEGORY_LABELS,
                        PERMISSION_LEVELS)
from app.decorators import require_admin
from app.audit import record as audit_record

bp = Blueprint('users', __name__)


@bp.route('/audit')
@login_required
@require_admin
def audit():
    from app.models import (AccountHistory, CertificateHistory, BackupHistory,
                            TestHistory, DomainHistory, ReviewHistory, UpdateHistory,
                            ActionLog)
    rows = []

    CAP = 3000  # borne par source pour limiter la memoire

    def collect(model, fk, cat, endpoint):
        for h in model.query.order_by(model.performed_at.desc()).limit(CAP).all():
            rows.append({
                'when': h.performed_at, 'cat': cat, 'action': h.action,
                'comment': getattr(h, 'comment', None), 'by': h.performed_by,
                'url': url_for(endpoint, id=getattr(h, fk)),
            })

    collect(AccountHistory, 'account_id', 'Compte', 'accounts.detail')
    collect(CertificateHistory, 'certificate_id', 'Certificat', 'certificates.detail')
    collect(DomainHistory, 'domain_id', 'Domaine', 'domains.detail')
    collect(BackupHistory, 'backup_id', 'Backup', 'backups.detail')
    collect(TestHistory, 'test_id', 'Test', 'tests.detail')
    collect(ReviewHistory, 'review_id', 'Revue', 'reviews.detail')
    collect(UpdateHistory, 'update_id', 'Mise a jour', 'updates.detail')

    # Journal d'actions central (login, corbeille, roles, config...) sans lien.
    for a in ActionLog.query.order_by(ActionLog.performed_at.desc()).limit(CAP).all():
        rows.append({
            'when': a.performed_at, 'cat': a.category or 'Système', 'action': a.action,
            'comment': a.detail, 'by': a.username, 'url': None,
        })

    # Recherche plein-texte simple (action / detail / auteur / categorie)
    q = (request.args.get('q') or '').strip()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in ' '.join(
            str(r.get(k) or '') for k in ('action', 'comment', 'by', 'cat')).lower()]

    rows.sort(key=lambda r: r['when'], reverse=True)

    # Pagination
    per_page = 50
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    total = len(rows)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    return render_template('users/audit.html', rows=page_rows, q=q,
                           page=page, pages=pages, total=total)


@bp.route('/roles')
@login_required
@require_admin
def roles():
    roles = Role.query.order_by(Role.id).all()
    counts = {r.name: User.query.filter_by(role=r.name).count() for r in roles}
    return render_template('users/roles.html', roles=roles, counts=counts,
                           categories=PERMISSION_CATEGORIES, labels=CATEGORY_LABELS,
                           levels=PERMISSION_LEVELS)


@bp.route('/roles/<int:id>/save', methods=['POST'])
@login_required
@require_admin
def roles_save(id):
    role = Role.query.get_or_404(id)
    role.description = request.form.get('description', role.description)
    if not role.is_admin:
        perms = {}
        for c in PERMISSION_CATEGORIES:
            try:
                lvl = int(request.form.get(f'perm_{c}', 0))
            except (TypeError, ValueError):
                lvl = 0
            perms[c] = max(0, min(3, lvl))
        role.permissions = perms
    db.session.commit()
    audit_record('modification role', detail=role.name, category='roles')
    flash(f'Role « {role.name} » enregistre', 'success')
    return redirect(url_for('users.roles'))


@bp.route('/roles/create', methods=['POST'])
@login_required
@require_admin
def roles_create():
    name = (request.form.get('name') or '').strip().lower()
    if not name:
        flash('Nom de role requis.', 'danger')
        return redirect(url_for('users.roles'))
    if Role.query.filter_by(name=name).first():
        flash('Ce role existe deja.', 'danger')
        return redirect(url_for('users.roles'))
    db.session.add(Role(name=name, description=request.form.get('description', ''),
                        is_admin=False, permissions={c: 0 for c in PERMISSION_CATEGORIES}))
    db.session.commit()
    audit_record('creation role', detail=name, category='roles')
    flash(f'Role « {name} » cree.', 'success')
    return redirect(url_for('users.roles'))


@bp.route('/roles/<int:id>/delete', methods=['POST'])
@login_required
@require_admin
def roles_delete(id):
    role = Role.query.get_or_404(id)
    if role.name in ('admin', 'editor', 'viewer'):
        flash('Les roles par defaut ne peuvent pas etre supprimes.', 'danger')
        return redirect(url_for('users.roles'))
    if User.query.filter_by(role=role.name).count() > 0:
        flash('Role utilise par des utilisateurs : reassignez-les d abord.', 'danger')
        return redirect(url_for('users.roles'))
    _rname = role.name
    db.session.delete(role)
    db.session.commit()
    audit_record('suppression role', detail=_rname, category='roles')
    flash('Role supprime.', 'success')
    return redirect(url_for('users.roles'))


@bp.route('/')
@login_required
def list():
    if not current_user.is_admin:
        flash('Acces refuse', 'danger')
        return redirect(url_for('dashboard.index'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/list.html', users=users)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.is_admin:
        flash('Acces refuse', 'danger')
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'viewer')
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur existe deja', 'danger')
            return render_template('users/form.html', user=None)
        if User.query.filter_by(email=email).first():
            flash('Cet email existe deja', 'danger')
            return render_template('users/form.html', user=None)
        minlen = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
        if len(password or '') < minlen:
            flash(f'Le mot de passe doit contenir au moins {minlen} caracteres', 'danger')
            return render_template('users/form.html', user=None)
        u = User(username=username, email=email, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        audit_record('creation utilisateur', detail=f'{username} (role {role})', category='utilisateurs')
        flash(f'Utilisateur {username} cree avec succes', 'success')
        return redirect(url_for('users.list'))
    return render_template('users/form.html', user=None)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not current_user.is_admin:
        flash('Acces refuse', 'danger')
        return redirect(url_for('dashboard.index'))
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.email = request.form.get('email')
        user.role = request.form.get('role', 'viewer')
        new_password = request.form.get('password')
        minlen = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
        if new_password and len(new_password) >= minlen:
            user.set_password(new_password)
        elif new_password and len(new_password) < minlen:
            flash(f'Le mot de passe doit contenir au moins {minlen} caracteres', 'danger')
            return render_template('users/form.html', user=user)
        db.session.commit()
        audit_record('modification utilisateur', detail=f'{user.username} (role {user.role})', category='utilisateurs')
        flash(f'Utilisateur {user.username} modifie', 'success')
        return redirect(url_for('users.list'))
    return render_template('users/form.html', user=user)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_admin:
        flash('Acces refuse', 'danger')
        return redirect(url_for('dashboard.index'))
    user = User.query.get_or_404(id)
    if user.username == 'admin':
        flash('Impossible de supprimer l\'administrateur principal', 'danger')
        return redirect(url_for('users.list'))
    if user.id == current_user.id:
        flash('Vous ne pouvez pas supprimer votre propre compte', 'danger')
        return redirect(url_for('users.list'))
    _uname = user.username
    db.session.delete(user)
    db.session.commit()
    audit_record('suppression utilisateur', detail=_uname, category='utilisateurs')
    flash(f'Utilisateur {_uname} supprime', 'success')
    return redirect(url_for('users.list'))
