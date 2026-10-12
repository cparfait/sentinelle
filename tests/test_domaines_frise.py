"""Le dernier renouvellement d'un domaine (Domain.renewed_on) : lu au registre
(RDAP, evenement « last changed », a defaut l'enregistrement) ou saisi, il
donne au bandeau de la fiche sa frise, du renouvellement a l'expiration —
comme les autres fiches."""
from datetime import date

from app import db
from app.models import Domain
from app.domain_checker import fetch_domain_info
from app.domains import refresh_domain_rdap


class _Reponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _rdap(monkeypatch, events):
    data = {'events': events, 'entities': []}
    monkeypatch.setattr('app.domain_checker.http_requests.get', lambda *a, **k: _Reponse(data))


def test_le_rdap_donne_le_dernier_renouvellement(monkeypatch):
    _rdap(monkeypatch, [
        {'eventAction': 'registration', 'eventDate': '2015-03-01T10:00:00Z'},
        {'eventAction': 'last changed', 'eventDate': '2026-02-28T09:30:00Z'},
        {'eventAction': 'expiration', 'eventDate': '2027-03-01T00:00:00Z'},
    ])
    info = fetch_domain_info('exemple.fr')
    assert info['expiry_date'] == date(2027, 3, 1)
    assert info['renewed_on'] == date(2026, 2, 28)


def test_sans_dernier_changement_l_enregistrement_fait_le_debut(monkeypatch):
    _rdap(monkeypatch, [
        {'eventAction': 'registration', 'eventDate': '2015-03-01T10:00:00Z'},
        {'eventAction': 'expiration', 'eventDate': '2027-03-01T00:00:00Z'},
    ])
    assert fetch_domain_info('exemple.fr')['renewed_on'] == date(2015, 3, 1)


def test_un_debut_apres_l_expiration_ne_compte_pas(monkeypatch):
    _rdap(monkeypatch, [
        {'eventAction': 'last changed', 'eventDate': '2027-06-01T00:00:00Z'},
        {'eventAction': 'expiration', 'eventDate': '2027-03-01T00:00:00Z'},
    ])
    assert fetch_domain_info('exemple.fr')['renewed_on'] is None


def test_verifier_au_registre_pose_le_renouvellement(client, monkeypatch):
    d = Domain(name='registre.fr', expiry_date=date(2026, 1, 1))
    db.session.add(d)
    db.session.commit()
    monkeypatch.setattr('app.domains.fetch_domain_info', lambda name: {
        'expiry_date': date(2027, 1, 1), 'renewed_on': date(2026, 1, 1), 'registrar': 'OVH'})
    ok, _ = refresh_domain_rdap(d, 'admin')
    db.session.commit()
    assert ok and d.renewed_on == date(2026, 1, 1) and d.expiry_date == date(2027, 1, 1)


def test_la_frise_du_domaine_part_du_dernier_renouvellement(client):
    sans = Domain(name='sans.fr', expiry_date=date(2030, 1, 1))
    avec = Domain(name='avec.fr', expiry_date=date(2030, 1, 1), renewed_on=date(2029, 1, 1))
    db.session.add_all([sans, avec])
    db.session.commit()
    assert 'fiche-frise' not in client.get(f'/domains/{sans.id}').get_data(as_text=True)
    html = client.get(f'/domains/{avec.id}').get_data(as_text=True)
    assert 'fiche-frise' in html and '01/01/2029' in html


def test_le_formulaire_enregistre_le_renouvellement(client):
    d = Domain(name='form.fr', expiry_date=date(2030, 1, 1))
    db.session.add(d)
    db.session.commit()
    client.post(f'/domains/{d.id}/edit', follow_redirects=True,
                data={'name': 'form.fr', 'expiry_date': '2030-01-01', 'renewed_on': '2029-01-01'})
    assert db.session.get(Domain, d.id).renewed_on == date(2029, 1, 1)
