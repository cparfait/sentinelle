"""Tests de l'API Sesame (GET /api/assets) : activation, clé Bearer, format.

Contrat attendu par Sesame : tableau JSON [{id, name, description, is_active}]
trié par nom, auth `Authorization: Bearer <clé>`, filtre `?type=`.
"""
from app import db
from app.models import Asset


def _seed_assets():
    db.session.add(Asset(name='Zabbix', asset_type='application', description='Supervision'))
    db.session.add(Asset(name='GLPI', asset_type='application', description='Parc'))
    db.session.add(Asset(name='Divers X', asset_type='divers', description='Autre'))
    db.session.commit()


def test_desactive_renvoie_503(app):
    app.config['SESAME_API_ENABLED'] = False
    app.config['SESAME_API_TOKEN'] = 'k'
    r = app.test_client().get('/api/assets')
    assert r.status_code == 503


def test_sans_cle_renvoie_401(app):
    app.config['SESAME_API_ENABLED'] = True
    app.config['SESAME_API_TOKEN'] = 'bonne-cle'
    c = app.test_client()
    assert c.get('/api/assets').status_code == 401
    assert c.get('/api/assets', headers={'Authorization': 'Bearer mauvaise'}).status_code == 401


def test_non_configuree_renvoie_503(app):
    app.config['SESAME_API_ENABLED'] = True
    app.config['SESAME_API_TOKEN'] = ''
    r = app.test_client().get('/api/assets', headers={'Authorization': 'Bearer x'})
    assert r.status_code == 503


def test_liste_applications_triee(app):
    _seed_assets()
    app.config['SESAME_API_ENABLED'] = True
    app.config['SESAME_API_TOKEN'] = 'bonne-cle'
    r = app.test_client().get('/api/assets?type=application',
                              headers={'Authorization': 'Bearer bonne-cle'})
    assert r.status_code == 200
    data = r.get_json()
    assert [a['name'] for a in data] == ['GLPI', 'Zabbix']   # trié, 'divers' exclu
    a = data[0]
    assert set(a.keys()) == {'id', 'name', 'description', 'is_active'}
    assert a['is_active'] is True


def test_sans_filtre_type_renvoie_tout(app):
    _seed_assets()
    app.config['SESAME_API_ENABLED'] = True
    app.config['SESAME_API_TOKEN'] = 'bonne-cle'
    r = app.test_client().get('/api/assets', headers={'Authorization': 'Bearer bonne-cle'})
    assert r.status_code == 200
    assert {a['name'] for a in r.get_json()} == {'GLPI', 'Zabbix', 'Divers X'}
