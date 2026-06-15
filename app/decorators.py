from functools import wraps
from flask import flash, redirect, url_for, request
from flask_login import current_user

# La categorie de permission est deduite du blueprint courant.
_BP_CATEGORY = {
    'accounts': 'accounts', 'certificates': 'certificates', 'domains': 'domains',
    'backups': 'backups', 'tests': 'tests', 'reviews': 'reviews',
    'updates': 'updates', 'inventory': 'inventory', 'alerts': 'alerts',
    # Contrats et annuaire fournisseurs partagent la meme categorie de droits.
    'contracts': 'contracts', 'suppliers': 'contracts',
}


def _category():
    return _BP_CATEGORY.get(request.blueprint)


def _deny():
    flash("Vous n'avez pas les droits pour effectuer cette action.", 'danger')
    return redirect(url_for('dashboard.index'))


def require_edit(view):
    """Exige le droit d'ecriture sur la categorie du blueprint courant."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return _deny()
        cat = _category()
        if not (current_user.can_edit(cat) if cat else current_user.can_edit()):
            return _deny()
        return view(*args, **kwargs)
    return wrapped


def require_delete(view):
    """Exige le droit de suppression sur la categorie du blueprint courant."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return _deny()
        cat = _category()
        ok = current_user.can_delete(cat) if cat else current_user.can_edit()
        if not ok:
            return _deny()
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


def view_guard(category):
    """A utiliser dans un before_request : bloque l'acces en lecture a une
    categorie si l'utilisateur connecte n'a pas le droit de la voir."""
    if current_user.is_authenticated and not current_user.can_view(category):
        flash("Acces non autorise a cette section.", 'danger')
        return redirect(url_for('dashboard.index'))
    return None
