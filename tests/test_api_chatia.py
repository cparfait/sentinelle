"""API de chatIA (GET /api/chatia/...) : sa clé à lui, la lecture seule, et
surtout ce qui ne sort jamais — aucun secret, aucun texte libre.

Contrat attendu par le connecteur de chatIA :
- /api/chatia/echeances?dans=<jours>&type=<types> -> {dans, jusqu_au, total,
  en_retard, tronque, elements: [{type, type_libelle, id, nom, objet, echeance,
  jours_restants, en_retard, detail, statut, statut_libelle, responsable,
  reporte_jusqu_au, lien}]} ;
- /api/chatia/alertes?type=<types>&reportees=1 -> {total, critiques, urgentes,
  reportees_incluses, tronque, elements} : une ligne par fiche critique ou urgente ;
- /api/chatia/synthese -> {categories, totaux, conformite, alertes} ;
- /api/chatia/recherche?q=<texte> -> {q, total, tronque, elements (+ details)}.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.models import (Account, AccessReview, AlertLog, AlertSnooze, AppConfig, Backup,
                        BackupCheck, Certificate, Contract, Domain, Equipment, Software,
                        Supplier, SystemUpdate, TestTask)

CLE = 'cle-chatia-de-test'
ENTETE = {'Authorization': f'Bearer {CLE}'}
ROUTES = ('/api/chatia/echeances', '/api/chatia/alertes', '/api/chatia/synthese',
          '/api/chatia/recherche?q=portail')


def _jour(n):
    return datetime.now(timezone.utc).date() + timedelta(days=n)


@pytest.fixture()
def api(app):
    app.config['CHATIA_API_ENABLED'] = True
    app.config['CHATIA_API_TOKEN'] = CLE
    app.config['APP_BASE_URL'] = 'https://sentinelle.ville.local/'
    return app.test_client()


def _lire(client, chemin):
    r = client.get(chemin, headers=ENTETE)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _peupler():
    """Un échantillon de chaque famille, avec des secrets là où la base en a."""
    sup = Supplier(name='Certinomis', kind='ca')
    db.session.add(sup)
    db.session.commit()
    db.session.add_all([
        Certificate(service_name='Portail', domain='www.mairie.fr', expiry_date=_jour(10),
                    description='mdp du keystore : Secret-Keystore-42'),
        Certificate(kind='signature', service_name='Élus', holder='EXEMPLE', first_name='Anne',
                    civility='mme', expiry_date=_jour(20), supplier_id=sup.id,
                    revocation_code='REVOC-SECRET-9876'),
        Certificate(service_name='Ancien', domain='old.mairie.fr', expiry_date=_jour(5),
                    validity='revoque'),
        Certificate(service_name='Commande', domain='new.mairie.fr'),  # sans date
        Domain(name='mairie.fr', expiry_date=_jour(100), registrar='Gandi'),
        Account(service_name='GLPI', username='svc-admin', next_password_change=_jour(-3),
                description='Mot de passe actuel : Hunter2-Secret'),
        Backup(service_name='Veeam serveurs', frequency='daily'),
        TestTask(name='PRA annuel', test_type='PRA', next_due=_jour(25)),
        AccessReview(application='e.magnus', responsible='Martine Dupuis',
                     next_review=_jour(40), scope='Comptes : voir le classeur protégé'),
        SystemUpdate(name='Zimbra', status='critical', current_version='9.0',
                     latest_version='10.1'),
        SystemUpdate(name='Firefox', status='up_to_date'),
        Contract(name='Maintenance pare-feu', end_date=_jour(70), notice_days=60),
        Equipment(name='SRV-AD01', kind='physical', warranty_end=_jour(15)),
        Software(name='Ciril', lifecycle='fin_de_vie', responsible='Paul Martin'),
    ])
    db.session.commit()
    sauvegarde = Backup.query.filter_by(service_name='Veeam serveurs').one()
    db.session.add(BackupCheck(backup_id=sauvegarde.id, check_date=_jour(0), status='failed'))
    db.session.commit()


# ── Accès ──

@pytest.mark.parametrize('chemin', ROUTES)
def test_desactivee_renvoie_503(app, chemin):
    app.config['CHATIA_API_ENABLED'] = False
    app.config['CHATIA_API_TOKEN'] = CLE
    assert app.test_client().get(chemin, headers=ENTETE).status_code == 503


@pytest.mark.parametrize('chemin', ROUTES)
def test_sans_cle_ou_mauvaise_cle_renvoie_401(api, chemin):
    assert api.get(chemin).status_code == 401
    assert api.get(chemin, headers={'Authorization': 'Bearer mauvaise'}).status_code == 401


def test_cle_absente_renvoie_503(app):
    app.config['CHATIA_API_ENABLED'] = True
    app.config['CHATIA_API_TOKEN'] = ''
    r = app.test_client().get('/api/chatia/synthese', headers={'Authorization': 'Bearer x'})
    assert r.status_code == 503


def test_la_cle_de_sesame_n_ouvre_pas_chatia(api, app):
    """Une clé par consommateur : celle de Sesame ne vaut pas pour chatIA, et
    inversement."""
    app.config['SESAME_API_ENABLED'] = True
    app.config['SESAME_API_TOKEN'] = 'cle-sesame'
    assert api.get('/api/chatia/synthese',
                   headers={'Authorization': 'Bearer cle-sesame'}).status_code == 401
    assert api.get('/api/assets', headers=ENTETE).status_code == 401


def test_lecture_seule(api):
    for chemin in ROUTES:
        assert api.post(chemin, headers=ENTETE).status_code == 405


def test_reponses_non_mises_en_cache(api):
    r = api.get('/api/chatia/synthese', headers=ENTETE)
    assert r.headers['Cache-Control'] == 'no-store'


# ── Échéances ──

def test_echeances_dans_l_horizon_et_en_retard(api):
    _peupler()
    data = _lire(api, '/api/chatia/echeances?dans=30')
    noms = [e['nom'] for e in data['elements']]
    assert data['dans'] == 30 and data['jusqu_au'] == _jour(30).isoformat()
    # Datées, dans les 30 jours ou dépassées
    assert 'Portail - www.mairie.fr' in noms
    assert 'Élus - Mme EXEMPLE Anne' in noms
    assert 'GLPI (svc-admin)' in noms                 # en retard de 3 jours
    assert 'PRA annuel' in noms
    assert 'SRV-AD01 (garantie)' in noms
    assert 'Maintenance pare-feu' in noms             # fin à 70 j, préavis de 60 j
    # D'état, quel que soit l'horizon
    assert 'Veeam serveurs' in noms                   # contrôle du jour en échec
    assert 'Zimbra' in noms                           # mise à jour critique
    assert 'Ciril' in noms                            # fin de vie
    # Hors horizon, hors surveillance ou rien à faire
    assert 'mairie.fr' not in noms                    # dans 100 jours
    assert 'e.magnus' not in noms                     # dans 40 jours
    assert 'Ancien - old.mairie.fr' not in noms       # révoqué
    assert 'Commande - new.mairie.fr' not in noms     # sans date : à compléter, pas une échéance
    assert 'Firefox' not in noms                      # à jour
    assert data['en_retard'] == 1 and data['total'] == len(noms)


def test_le_preavis_d_un_contrat_fait_son_echeance(api):
    """Un contrat s'annonce à la date où il faut agir (fin - préavis), pas à sa fin."""
    db.session.add(Contract(name='Licences', end_date=_jour(50), notice_days=30))
    db.session.commit()
    data = _lire(api, '/api/chatia/echeances?dans=30')
    contrat = next(e for e in data['elements'] if e['nom'] == 'Licences')
    assert contrat['echeance'] == _jour(20).isoformat() and contrat['jours_restants'] == 20
    assert 'préavis 30 j' in contrat['detail']


def test_forme_d_un_element(api):
    _peupler()
    data = _lire(api, '/api/chatia/echeances?type=certificat')
    portail = next(e for e in data['elements'] if e['nom'] == 'Portail - www.mairie.fr')
    assert set(portail) >= {'type', 'type_libelle', 'id', 'nom', 'objet', 'echeance',
                            'jours_restants', 'en_retard', 'detail', 'statut', 'statut_libelle',
                            'responsable', 'reporte_jusqu_au', 'lien'}
    assert portail['type'] == 'certificat' and portail['type_libelle'] == 'Certificat TLS'
    assert portail['jours_restants'] == 10 and portail['en_retard'] is False
    assert portail['statut'] == 'warning' and portail['statut_libelle'] == 'Urgent'
    assert portail['detail'] == 'Certificat expire dans 10 j'
    assert portail['lien'] == f"https://sentinelle.ville.local/certificates/{portail['id']}"
    elus = next(e for e in data['elements'] if e['type_libelle'] == 'Certificat électronique')
    assert elus['titulaire'] == 'Mme EXEMPLE Anne'


def test_retard_et_responsable(api):
    _peupler()
    data = _lire(api, '/api/chatia/echeances?dans=60&type=mot_de_passe,revue')
    assert {e['type'] for e in data['elements']} == {'mot_de_passe', 'revue'}
    compte = next(e for e in data['elements'] if e['type'] == 'mot_de_passe')
    assert compte['en_retard'] is True and compte['jours_restants'] == -3
    assert compte['detail'] == 'Mot de passe à renouveler en retard de 3 j'
    revue = next(e for e in data['elements'] if e['type'] == 'revue')
    assert revue['responsable'] == 'Martine Dupuis'


def test_types_repetes_ou_separes_par_des_virgules(api):
    _peupler()
    a = _lire(api, '/api/chatia/echeances?type=sauvegarde&type=mise_a_jour')
    b = _lire(api, '/api/chatia/echeances?type=sauvegarde,mise_a_jour')
    assert a['elements'] == b['elements'] and a['types'] == ['sauvegarde', 'mise_a_jour']
    assert {e['nom'] for e in a['elements']} == {'Veeam serveurs', 'Zimbra'}
    zimbra = next(e for e in a['elements'] if e['nom'] == 'Zimbra')
    assert zimbra['echeance'] is None and zimbra['detail'] == 'Mise à jour critique (9.0 → 10.1)'


def test_report_signale(api):
    _peupler()
    portail = Certificate.query.filter_by(service_name='Portail').one()
    db.session.add(AlertSnooze(entity_type='certificate', entity_id=portail.id,
                               snoozed_until=_jour(7)))
    db.session.commit()
    data = _lire(api, '/api/chatia/echeances?type=certificat')
    el = next(e for e in data['elements'] if e['id'] == portail.id)
    assert el['reporte_jusqu_au'] == _jour(7).isoformat()


@pytest.mark.parametrize('requete', ['dans=-1', 'dans=abc', 'dans=9999', 'type=imprimante'])
def test_parametres_invalides_renvoient_400(api, requete):
    r = api.get(f'/api/chatia/echeances?{requete}', headers=ENTETE)
    assert r.status_code == 400 and r.get_json()['error']


def test_module_certificats_coupe(api, app):
    _peupler()
    app.config['CERTIFICATES_ENABLED'] = False
    data = _lire(api, '/api/chatia/echeances')
    assert 'certificat' not in data['types']
    assert all(e['type'] != 'certificat' for e in data['elements'])
    assert all(c['type'] != 'certificat' for c in _lire(api, '/api/chatia/synthese')['categories'])


# ── Synthèse ──

def test_synthese_par_type_et_statut(api):
    _peupler()
    db.session.add(AlertLog(alert_type='email', entity_type='certificate', entity_id=1,
                            entity_name='Portail - www.mairie.fr', status='sent',
                            message='corps du mail', recipients='dsi@ville.fr'))
    db.session.add(AlertLog(alert_type='email', entity_type='account', entity_id=1,
                            entity_name='GLPI (svc-admin)', status='failed',
                            message='ERREUR: SMTP 535 mot de passe refusé',
                            recipients='dsi@ville.fr'))
    db.session.commit()
    data = _lire(api, '/api/chatia/synthese')
    par_type = {c['type']: c for c in data['categories']}
    assert par_type['certificat']['total'] == 4
    assert par_type['mise_a_jour']['par_statut'] == {'danger': 1, 'warning': 0, 'info': 0,
                                                       'success': 1}
    assert data['totaux']['total'] == sum(c['total'] for c in data['categories'])
    assert 0 <= data['conformite'] <= 100
    alertes = data['alertes']
    assert alertes['critiques'] >= 3          # compte en retard, sauvegarde, Zimbra
    assert alertes['ouvertes'] == alertes['critiques'] + alertes['urgentes']
    assert alertes['envoyees_7_jours'] == 1 and alertes['echecs_7_jours'] == 1
    assert alertes['dernieres'][0]['type'] in ('certificat', 'mot_de_passe')
    assert set(alertes['dernieres'][0]) == {'date', 'type', 'nom', 'envoyee'}
    assert data['lien'] == 'https://sentinelle.ville.local/'


def test_une_alerte_reportee_n_est_plus_ouverte(api):
    db.session.add(SystemUpdate(name='Zimbra', status='critical'))
    db.session.commit()
    avant = _lire(api, '/api/chatia/synthese')['alertes']
    u = SystemUpdate.query.one()
    db.session.add(AlertSnooze(entity_type='update', entity_id=u.id, snoozed_until=_jour(7)))
    db.session.commit()
    apres = _lire(api, '/api/chatia/synthese')['alertes']
    assert avant['critiques'] == 1 and apres['critiques'] == 0 and apres['reportees'] == 1


# ── Alertes ──

def test_alertes_detaillent_les_comptes_de_la_synthese(api):
    """« Liste moi les alertes » (DSI, 11/10/2026) : une ligne par fiche critique
    ou urgente, la règle de la synthèse — les comptes concordent, type par type,
    fiches sans date comprises."""
    _peupler()
    resume = _lire(api, '/api/chatia/synthese')['alertes']
    data = _lire(api, '/api/chatia/alertes')
    assert (data['total'], data['critiques'], data['urgentes']) == (
        resume['ouvertes'], resume['critiques'], resume['urgentes'])
    par_type = {}
    for e in data['elements']:
        compte = par_type.setdefault(e['type'], {'critiques': 0, 'urgents': 0})
        compte['critiques' if e['statut'] == 'danger' else 'urgents'] += 1
    assert par_type == resume['par_type']
    noms = [e['nom'] for e in data['elements']]
    assert {'GLPI (svc-admin)', 'Veeam serveurs', 'Zimbra'} <= set(noms)
    assert 'Firefox' not in noms and 'mairie.fr' not in noms
    statuts = [e['statut'] for e in data['elements']]
    assert statuts == sorted(statuts, key=['danger', 'warning'].index)  # critiques d'abord
    assert not data['reportees_incluses'] and not data['tronque']


def test_alertes_materiel_par_fiche_et_filtre_par_type(api):
    _peupler()
    materiel = _lire(api, '/api/chatia/alertes?type=materiel')['elements']
    assert {e['type'] for e in materiel} <= {'materiel'}
    assert all('(garantie)' not in e['nom'] for e in materiel)  # la fiche, pas une échéance
    assert _lire(api, '/api/chatia/alertes?type=domaine')['total'] == 0


def test_alertes_reportees_a_la_demande(api):
    db.session.add(SystemUpdate(name='Zimbra', status='critical'))
    db.session.commit()
    u = SystemUpdate.query.one()
    db.session.add(AlertSnooze(entity_type='update', entity_id=u.id, snoozed_until=_jour(7)))
    db.session.commit()
    assert _lire(api, '/api/chatia/alertes')['total'] == 0
    data = _lire(api, '/api/chatia/alertes?reportees=1')
    assert data['total'] == 1 and data['reportees_incluses']
    assert data['elements'][0]['reporte_jusqu_au'] == _jour(7).isoformat()


# ── Recherche ──

def test_recherche_sans_accent_ni_majuscule(api):
    _peupler()
    data = _lire(api, '/api/chatia/recherche?q=elus')
    assert data['total'] == 1
    el = data['elements'][0]
    assert el['nom'] == 'Élus - Mme EXEMPLE Anne' and el['details']['autorite'] == 'Certinomis'
    assert _lire(api, '/api/chatia/recherche?q=EXEMPLE')['total'] == 1


def test_recherche_par_responsable_et_details(api):
    _peupler()
    data = _lire(api, '/api/chatia/recherche?q=dupuis')
    assert [e['nom'] for e in data['elements']] == ['e.magnus']
    assert data['elements'][0]['details']['frequence_jours'] == 365
    srv = _lire(api, '/api/chatia/recherche?q=srv-ad')['elements'][0]
    assert srv['type'] == 'materiel' and srv['details']['fin_garantie'] == _jour(15).isoformat()


def test_recherche_ne_lit_pas_les_textes_libres(api):
    _peupler()
    assert _lire(api, '/api/chatia/recherche?q=keystore')['total'] == 0
    assert _lire(api, '/api/chatia/recherche?q=hunter2')['total'] == 0


@pytest.mark.parametrize('q', ['', 'a', 'x' * 101])
def test_recherche_trop_courte_ou_trop_longue(api, q):
    assert api.get(f'/api/chatia/recherche?q={q}', headers=ENTETE).status_code == 400


# ── Jamais de secret ──

def test_aucun_secret_dans_aucune_reponse(api, app):
    _peupler()
    app.config['MAIL_PASSWORD'] = 'Mot-De-Passe-SMTP'
    db.session.add(AlertLog(alert_type='email', entity_type='account', entity_id=1,
                            entity_name='GLPI (svc-admin)', status='failed',
                            message='ERREUR: SMTP Mot-De-Passe-SMTP', recipients='dsi@ville.fr'))
    db.session.commit()
    corps = ''
    for chemin in ('/api/chatia/echeances?dans=730', '/api/chatia/alertes?reportees=1', '/api/chatia/synthese',
                   '/api/chatia/recherche?q=portail', '/api/chatia/recherche?q=elus',
                   '/api/chatia/recherche?q=glpi', '/api/chatia/recherche?q=e.magnus'):
        corps += json.dumps(_lire(api, chemin), ensure_ascii=False)
    for secret in ('REVOC-SECRET-9876', 'Secret-Keystore-42', 'Hunter2-Secret',
                   'classeur protégé', 'Mot-De-Passe-SMTP', 'dsi@ville.fr', CLE,
                   'revocation', 'description'):
        assert secret not in corps, secret


# ── Page Connecteurs ──

def test_page_connecteurs_annonce_chatia(app, client):
    body = client.get('/connecteurs/').data.decode('utf-8')
    assert 'chatIA' in body and 'chatia_enabled' in body and '/api/chatia/' in body
    assert 'Sesame' in body   # les deux cartes cohabitent


def test_activation_et_cle_chatia(app, client):
    app.config['CHATIA_API_ENABLED'] = False
    app.config['SESAME_API_TOKEN'] = 'cle-sesame-inchangee'
    client.post('/connecteurs/chatia', data={'action': 'save', 'chatia_enabled': 'on'})
    assert app.config['CHATIA_API_ENABLED'] is True
    r = client.post('/connecteurs/chatia', data={'action': 'generate_key'}, follow_redirects=True)
    cle = app.config['CHATIA_API_TOKEN']
    assert cle and len(cle) >= 20 and cle in r.data.decode('utf-8')   # montrée une fois
    assert app.config['SESAME_API_TOKEN'] == 'cle-sesame-inchangee'   # l'autre clé ne bouge pas
    # La clé est chiffrée en base, comme celle de Sesame.
    ligne = db.session.get(AppConfig, 'CHATIA_API_TOKEN')
    assert ligne.is_secret and cle not in (ligne.value or '')
    assert app.test_client().get('/api/chatia/synthese',
                                 headers={'Authorization': f'Bearer {cle}'}).status_code == 200
    client.post('/connecteurs/chatia', data={'action': 'save'})
    assert app.config['CHATIA_API_ENABLED'] is False


def test_connecteur_chatia_reserve_admin(app):
    from app.models import User
    u = User(username='lecteur', email='l@ex.fr', role='viewer')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'lecteur', 'password': 'x'})
    c.post('/connecteurs/chatia', data={'action': 'generate_key'})
    assert not app.config.get('CHATIA_API_TOKEN')
