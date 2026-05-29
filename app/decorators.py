from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user


def require_edit(view):
    """Autorise uniquement les roles capables de modifier (admin / editor)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_edit():
            flash("Vous n'avez pas les droits pour effectuer cette action.", 'danger')
            return redirect(url_for('dashboard.index'))
        return view(*args, **kwargs)
    return wrapped


def require_admin(view):
    """Autorise uniquement les administrateurs."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acces reserve aux administrateurs.', 'danger')
            return redirect(url_for('dashboard.index'))
        return view(*args, **kwargs)
    return wrapped
