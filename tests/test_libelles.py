"""Vocabulaire unique : un mot par couleur, des délais en français."""
from datetime import date, datetime, timedelta

from app.libelles import (status_label, status_label_plural, priority_label,
                          delai, jours, compte, date_longue, STATUS_LABELS)


def test_un_mot_par_couleur():
    assert status_label('danger') == 'Critique'
    assert status_label('warning') == 'Urgent'
    assert status_label('info') == 'À prévoir'
    assert status_label('success') == 'OK'
    assert status_label('pending') == 'Non suivi'
    assert status_label(None) == 'Non suivi'
    assert status_label('bizarre', fallback='?') == '?'
    assert len(set(STATUS_LABELS.values())) == 4


def test_pluriel_et_priorite():
    assert status_label_plural('danger') == 'critiques'
    assert status_label_plural('warning') == 'urgents'
    assert compte(1, 'danger') == '1 critique'
    assert compte(2, 'danger') == '2 critiques'
    assert compte(1, 'warning') == '1 urgent'
    assert compte(3, 'info') == '3 à prévoir'
    assert compte(4, 'success') == '4 OK'
    assert priority_label('high') == 'Haute'
    assert priority_label('critical') == 'Critique'
    assert priority_label(None) == ''
    assert priority_label('inconnue') == 'inconnue'


def test_delai_relatif():
    assert delai(-5) == 'en retard de 5 j'
    assert delai(0) == "aujourd'hui"
    assert delai(1) == 'demain'
    assert delai(12) == 'dans 12 j'
    assert delai(None) == ''
    assert delai('') == ''
    assert delai(-2, passe='expiré depuis') == 'expiré depuis 2 j'
    assert delai(-47, passe='préavis dépassé de') == 'préavis dépassé de 47 j'


def test_date_longue():
    assert date_longue(date(2026, 9, 17)) == 'jeudi 17 septembre 2026'
    assert date_longue(None) == ''


def test_delai_depuis_une_date():
    today = date(2026, 9, 17)
    assert jours(date(2026, 9, 29), today) == 12
    assert delai(date(2026, 9, 29), today=today) == 'dans 12 j'
    assert delai(datetime(2026, 9, 12, 8, 0), today=today) == 'en retard de 5 j'
    assert delai(date.today() + timedelta(days=3)) == 'dans 3 j'


def test_filtre_et_globaux_jinja(app):
    env = app.jinja_env
    assert env.filters['delai'](-3) == 'en retard de 3 j'
    tpl = env.from_string("{{ status_label('danger') }}|{{ priority_label('low') }}|{{ 4|delai }}")
    assert tpl.render() == 'Critique|Basse|dans 4 j'
