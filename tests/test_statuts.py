"""Paliers de statut (vert/orange/rouge) des modeles : c'est la logique dont
dependent le tableau de bord et toutes les alertes."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import (Account, Certificate, Domain, TestTask, AccessReview,
                        Backup, BackupCheck, Equipment, SystemUpdate)


def _day(offset):
    return datetime.now(timezone.utc).date() + timedelta(days=offset)


# ---- Seuils a date (comptes, certificats, domaines, tests, revues) ----

def test_certificat_paliers(app):
    # THRESHOLD_EXPIRY par defaut : danger <= 7, warning <= 15, info <= 30
    cases = [(-5, 'danger'), (0, 'danger'), (7, 'danger'), (8, 'warning'),
             (15, 'warning'), (16, 'info'), (30, 'info'), (31, 'success')]
    for days, attendu in cases:
        c = Certificate(service_name='svc', domain='exemple.fr', expiry_date=_day(days))
        assert c.status() == attendu, f'expiration J+{days} : {c.status()} != {attendu}'


def test_compte_paliers_et_sans_date(app):
    assert Account(service_name='s', username='u').status() == 'warning'
    assert Account(service_name='s', username='u',
                   next_password_change=_day(3)).status() == 'danger'
    assert Account(service_name='s', username='u',
                   next_password_change=_day(60)).status() == 'success'


def test_domaine_paliers(app):
    # THRESHOLD_DOMAIN par defaut : danger <= 30, warning <= 60, info <= 90
    cases = [(30, 'danger'), (31, 'warning'), (60, 'warning'),
             (61, 'info'), (90, 'info'), (91, 'success')]
    for days, attendu in cases:
        d = Domain(name='exemple.fr', expiry_date=_day(days))
        assert d.status() == attendu, f'expiration J+{days} : {d.status()} != {attendu}'
    assert Domain(name='sans-date.fr').status() == 'warning'


def test_test_recurrent_statuts(app):
    assert TestTask(name='t', test_type='pra', status='failed').computed_status() == 'danger'
    assert TestTask(name='t', test_type='pra', status='completed').computed_status() == 'success'
    assert TestTask(name='t', test_type='pra', status='pending').computed_status() == 'warning'  # sans next_due
    assert TestTask(name='t', test_type='pra', status='pending',
                    next_due=_day(5)).computed_status() == 'danger'
    assert TestTask(name='t', test_type='pra', status='pending',
                    next_due=_day(45)).computed_status() == 'success'


def test_revue_droits_statuts(app):
    assert AccessReview(application='a', status='failed').computed_status() == 'danger'
    assert AccessReview(application='a', status='pending').computed_status() == 'warning'
    assert AccessReview(application='a', status='pending',
                        next_review=_day(10)).computed_status() == 'warning'


def test_mise_a_jour_couleurs(app):
    cases = [('up_to_date', 'success'), ('update_available', 'warning'),
             ('critical', 'danger'), ('inconnu', 'info')]
    for status, attendu in cases:
        u = SystemUpdate(name='app', status=status)
        assert u.status_color() == attendu, f'{status} : {u.status_color()} != {attendu}'


# ---- Backups : statut selon la frequence et la tolerance ----

def _backup(freq):
    b = Backup(service_name=f'bkp-{freq}-{id(object())}', frequency=freq)
    db.session.add(b)
    db.session.commit()
    return b


def _check(backup, day_offset, status='ok'):
    """Check au jour J+offset (checked_at coherent avec check_date)."""
    db.session.add(BackupCheck(
        backup_id=backup.id, check_date=_day(day_offset), status=status,
        first_status=status,
        checked_at=datetime.now(timezone.utc) + timedelta(days=day_offset)))
    db.session.commit()


def test_backup_check_du_jour(app):
    for status, attendu in (('ok', 'success'), ('warning', 'warning'), ('failed', 'danger')):
        b = _backup('daily')
        _check(b, 0, status)
        assert b.computed_status() == attendu, f'check {status} : {b.computed_status()}'


def test_backup_quotidien_retard(app):
    # periode 1 j, tolerance 1 j : OK hier -> success, -2 j -> warning, -3 j -> danger
    for offset, attendu in ((-1, 'success'), (-2, 'warning'), (-3, 'danger')):
        b = _backup('daily')
        _check(b, offset, 'ok')
        assert b.computed_status() == attendu, f'dernier OK J{offset} : {b.computed_status()}'


def test_backup_hebdo_pas_en_retard_a_tort(app):
    # periode 7 j, tolerance 2 j : un hebdo vieux de 7 j est NORMAL.
    for offset, attendu in ((-7, 'success'), (-9, 'warning'), (-10, 'danger')):
        b = _backup('weekly')
        _check(b, offset, 'ok')
        assert b.computed_status() == attendu, f'dernier OK J{offset} : {b.computed_status()}'


def test_backup_mensuel(app):
    # periode 31 j, tolerance 5 j
    for offset, attendu in ((-31, 'success'), (-36, 'warning'), (-37, 'danger')):
        b = _backup('monthly')
        _check(b, offset, 'ok')
        assert b.computed_status() == attendu, f'dernier OK J{offset} : {b.computed_status()}'


def test_backup_sans_historique(app):
    assert _backup('daily').computed_status() == 'info'         # jamais verifie
    b = _backup('daily')
    _check(b, -1, 'failed')                                      # jamais OK
    assert b.computed_status() == 'warning'


# ---- Inventaire ----

def test_garantie_paliers(app):
    # THRESHOLD_WARRANTY par defaut : danger <= 30, warning <= 60, info <= 90
    cases = [(10, 'danger'), (45, 'warning'), (75, 'info'), (120, 'success')]
    for days, attendu in cases:
        e = Equipment(name='srv', warranty_end=_day(days))
        assert e.warranty_status() == attendu, f'garantie J+{days} : {e.warranty_status()}'
    assert Equipment(name='srv').warranty_status() is None


def test_criticite_sans_sauvegarde(app):
    e = Equipment(name='srv', criticality=3)
    db.session.add(e)
    db.session.commit()
    assert e.missing_backup() is True
    assert e.computed_status() == 'danger'
    # criticite faible : pas concerne
    assert Equipment(name='poste', criticality=2).missing_backup() is False
    # champ texte renseigne : couvert
    assert Equipment(name='srv2', criticality=4, backup1='Veeam').missing_backup() is False


def test_backup_lie_couvre_la_criticite(app):
    """Vue 360° : un backup actif lie a l'equipement vaut sauvegarde."""
    e = Equipment(name='srv-lie', criticality=4)
    db.session.add(e)
    db.session.commit()
    assert e.missing_backup() is True
    b = Backup(service_name='Backup srv-lie', frequency='daily', equipment_id=e.id)
    db.session.add(b)
    db.session.commit()
    assert e.missing_backup() is False
    # backup desactive (corbeille) : ne compte plus
    b.is_active = False
    db.session.commit()
    assert e.missing_backup() is True


def test_maj_os_obsolete(app):
    assert Equipment(name='e').os_update_stale() is False            # rien renseigne
    assert Equipment(name='e', os='Debian').os_update_stale() is True  # OS sans date
    assert Equipment(name='e', os='Debian',
                     os_last_update=_day(-400)).os_update_stale() is True
    assert Equipment(name='e', os='Debian',
                     os_last_update=_day(-100)).os_update_stale() is False
