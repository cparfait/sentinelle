from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import User

bp = Blueprint('users', __name__)


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
