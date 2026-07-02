"""Tests de la surveillance Certificate Transparency (ct_monitor / ct_checker).

On injecte un faux `fetcher` (pas d'appel reseau vers crt.sh) pour piloter les
certificats renvoyes et verifier : ligne de base silencieuse, detection des
nouveaux, deduplication, respect du snooze, et acquittement.
"""
from datetime import date, datetime, timezone

import pytest

from app import db
from app.models import Domain, CtLogEntry, AlertLog
from app import ct_monitor
from app.ct_checker import _clean_domain, _normalize, _parse_date


def _cert(cid, name='www.exemple.fr', issuer="Let's Encrypt"):
    return {
        'crtsh_id': cid, 'serial_number': f'{cid:x}', 'common_name': name,
        'name_value': name, 'issuer_name': issuer,
        'not_before': date(2026, 1, 1), 'not_after': date(2026, 4, 1),
        'entry_timestamp': datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def _make_domain():
    d = Domain(name='exemple.fr', is_active=True)
    db.session.add(d)
    db.session.commit()
    return d


@pytest.fixture(autouse=True)
def _no_real_mail(app, monkeypatch):
    """Neutralise l'envoi mail et fournit des destinataires pour que
    send_alert aille au bout (et journalise dans AlertLog)."""
    app.config['ALERT_RECIPIENTS'] = ['dsi@exemple.fr']
    monkeypatch.setattr('app.alerts.send_email', lambda *a, **k: None)


def _fetcher(certs):
    return lambda name: list(certs)


def test_premier_scan_etablit_ligne_de_base_sans_alerte(app):
    d = _make_domain()
    res = ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))

    assert res['baseline'] == 2
    assert res['new'] == []
    assert d.ct_last_id == 2
    assert CtLogEntry.query.filter_by(status='baseline').count() == 2
    # Aucune alerte CT pour l'historique.
    assert AlertLog.query.filter_by(entity_type='ct').count() == 0


def test_nouveau_certificat_detecte_et_alerte(app):
    d = _make_domain()
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))  # base
    res = ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2), _cert(3)]))

    assert len(res['new']) == 1
    assert res['new'][0].crtsh_id == 3
    assert res['new'][0].status == 'new'
    assert d.ct_last_id == 3
    # Une alerte CT a bien ete journalisee.
    assert AlertLog.query.filter_by(entity_type='ct', status='sent').count() == 1


def test_deduplication_pas_de_nouvelle_alerte(app):
    d = _make_domain()
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1)]))
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))  # 1 alerte
    res = ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))  # rien de neuf

    assert res['new'] == []
    assert CtLogEntry.query.count() == 2
    assert AlertLog.query.filter_by(entity_type='ct', status='sent').count() == 1


def test_snooze_supprime_l_alerte_mais_enregistre(app):
    from app.snooze import set_snooze
    d = _make_domain()
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1)]))  # base
    set_snooze('domain', d.id, 7, 'maintenance', 'admin')
    res = ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))

    assert len(res['new']) == 1                       # enregistre
    assert AlertLog.query.filter_by(entity_type='ct').count() == 0  # mais pas d'alerte


def test_scan_en_echec_journalise_sans_planter(app):
    d = _make_domain()

    def boom(name):
        raise RuntimeError('crt.sh injoignable')

    res = ct_monitor.scan_domain(d, fetcher=boom)
    assert res['error'] == 'crt.sh injoignable'
    assert d.ct_last_id is None  # pas de ligne de base sur echec


def test_acknowledge_via_route(client, app):
    d = _make_domain()
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1)]))
    ct_monitor.scan_domain(d, fetcher=_fetcher([_cert(1), _cert(2)]))
    assert d.ct_new_count() == 1

    r = client.post(f'/domains/{d.id}/ct-ack', follow_redirects=True)
    assert r.status_code == 200
    assert Domain.query.get(d.id).ct_new_count() == 0


# --- ct_checker : normalisation pure ---
def test_clean_domain():
    assert _clean_domain('https://www.Exemple.fr/path') == 'www.exemple.fr'
    assert _clean_domain('*.exemple.fr') == 'exemple.fr'
    assert _clean_domain('exemple.fr:443') == 'exemple.fr'


def test_normalize_ignore_id_absent():
    assert _normalize({'common_name': 'x'}) is None
    row = _normalize({'id': 42, 'name_value': 'a\nb', 'not_before': '2026-01-02T00:00:00'})
    assert row['crtsh_id'] == 42
    assert _parse_date('2026-01-02T00:00:00') == date(2026, 1, 2)
