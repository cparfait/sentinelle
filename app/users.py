from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import (User, Role, PERMISSION_CATEGORIES, CATEGORY_LABELS,
                        PERMISSION_LEVELS)
from app.decorators import require_admin

bp = Blueprint('users', __name__)


@bp.route('/audit')
@login_required
@require_admin
def audit():
    from app.models import (AccountHistory, CertificateHistory, BackupHistory,
                            TestHistory, DomainHistory)
    rows = []

    def collect(model, fk, cat, endpoint):
        for h in model.query.order_by(model.performed_at.desc()).limit(200).all():
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

    rows.sort(key=lambda r: r['when'], reverse=True)
    return render_template('users/audit.html', rows=rows[:200])


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
    db.session.delete(role)
    db.session.commit()
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
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caracteres', 'danger')
            return render_template('users/form.html', user=None)
        u = User(username=username, email=email, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
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
        if new_password and len(new_password) >= 8:
            user.set_password(new_password)
        elif new_password and len(new_password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caracteres', 'danger')
            return render_template('users/form.html', user=user)
        db.session.commit()
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
    db.session.delete(user)
    db.session.commit()
    flash(f'Utilisateur {user.username} supprime', 'success')
    return redirect(url_for('users.list'))
