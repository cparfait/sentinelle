"""Politique de rappel des alertes (rattrapage) et reports (snooze)."""
from datetime import datetime, timezone, timedelta

from app import db
from app.alerts import should_send_reminder
from app.models import AlertLog
from app.snooze import is_snoozed, set_snooze, clear_snooze

TH = (7, 15, 30)  # (danger, warning, info)


def _log(days_ago, status='sent'):
    db.session.add(AlertLog(
        alert_type='email', entity_type='certificate', entity_id=42,
        sent_at=datetime.now(timezone.utc) - timedelta(days=days_ago), status=status))
    db.session.commit()


def test_hors_fenetre_pas_d_alerte(app):
    assert should_send_reminder('certificate', 42, 45, TH) is False


def test_premiere_alerte_dans_la_fenetre(app):
    assert should_send_reminder('certificate', 42, 20, TH) is True


def test_cadence_warning_7_jours(app):
    _log(days_ago=1)
    assert should_send_reminder('certificate', 42, 20, TH) is False  # rappel trop recent
    AlertLog.query.delete()
    _log(days_ago=8)
    assert should_send_reminder('certificate', 42, 20, TH) is True   # rattrapage


def test_cadence_danger_2_jours(app):
    _log(days_ago=1)
    assert should_send_reminder('certificate', 42, 5, TH) is False
    AlertLog.query.delete()
    _log(days_ago=2)
    assert should_send_reminder('certificate', 42, 5, TH) is True


def test_echu_rappel_quotidien(app):
    _log(days_ago=1)
    assert should_send_reminder('certificate', 42, -3, TH) is True


def test_envoi_echoue_ne_bloque_pas(app):
    _log(days_ago=0, status='failed')
    assert should_send_reminder('certificate', 42, 20, TH) is True


def test_alerte_d_une_autre_entite_sans_effet(app):
    _log(days_ago=0)
    # meme type mais autre id : la cadence ne s'applique pas
    assert should_send_reminder('certificate', 43, 20, TH) is True


def test_snooze(app):
    assert is_snoozed('certificate', 42) is False
    set_snooze('certificate', 42, days=7, reason='renouvellement en cours')
    assert is_snoozed('certificate', 42) is True
    clear_snooze('certificate', 42)
    assert is_snoozed('certificate', 42) is False


def test_snooze_expire(app):
    set_snooze('certificate', 42, days=-1)  # report deja depasse
    assert is_snoozed('certificate', 42) is False


def test_destinataires_par_categorie(app):
    from app.alerts import alert_recipients_for
    app.config['ALERT_RECIPIENTS'] = ['dsi@mairie.fr']
    app.config['ALERT_RECIPIENTS_BACKUP'] = ['sauvegarde@mairie.fr']
    app.config['ALERT_RECIPIENTS_CERTIFICATE'] = []
    # liste dediee definie -> elle prime
    assert alert_recipients_for('backup') == ['sauvegarde@mairie.fr']
    # liste dediee vide -> repli sur la globale
    assert alert_recipients_for('certificate') == ['dsi@mairie.fr']
    # pas de type -> globale
    assert alert_recipients_for(None) == ['dsi@mairie.fr']


def test_seuils_invalides_pas_d_alerte(app):
    assert should_send_reminder('certificate', 42, 5, None) is False
    assert should_send_reminder('certificate', 42, 5, (7, 15)) is False
