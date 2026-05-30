"""Journal d'actions central : enregistre qui fait quoi (persiste meme apres
suppression definitive de l'element concerne)."""
from flask_login import current_user
from app import db
from app.models import ActionLog


def record(action, detail='', category=None):
    """Enregistre une action au nom de l'utilisateur connecte."""
    try:
        username = current_user.username if getattr(current_user, 'is_authenticated', False) else 'anonyme'
    except Exception:
        username = 'system'
    db.session.add(ActionLog(username=username, action=action,
                             category=category, detail=detail or None))
    db.session.commit()
