"""Certificats électroniques nominatifs (RGS / eIDAS) : ils partagent la table,
les alertes et l'agenda des certificats TLS — même échéance, même surveillance."""
from datetime import date, timedelta

from app import db
from app.models import Certificate, Supplier, Referential


def _demain(n):
    return date.today() + timedelta(days=n)


def test_creation_d_un_certificat_electronique(client):
    ca = Supplier(name='Certinomis', kind='ca')
    db.session.add(ca)
    db.session.commit()
    sv = Referential(kind='user_service', label='État civil')
    db.session.add(sv)
    db.session.commit()

    client.post('/certificates/create', data={
        'kind': 'signature', 'service_name': 'Signature des marchés',
        'civility': 'mme', 'first_name': 'Claire', 'holder': 'ARNAUD',
        'holder_role': 'Adjointe', 'holder_email': 'c.arnaud@ville.fr',
        'supplier_id': str(ca.id), 'service_id': str(sv.id),
        'cert_usage': 'signature', 'support': 'carte', 'level': 'RGS**',
        'serial_number': 'A1B2C3', 'duration_years': '3',
        'amount_ttc': '120,50', 'budget_code': '60632',
        'order_signed_on': '2026-01-15', 'revocation_code': 'SECRET-42',
        'expiry_date': _demain(400).isoformat(), 'validity': 'valide',
    }, follow_redirects=True)

    c = Certificate.query.filter_by(service_name='Signature des marchés').one()
    assert c.kind == 'signature' and c.domain is None
    assert c.holder_label() == 'Mme Claire ARNAUD'
    assert c.label() == 'Signature des marchés - Mme Claire ARNAUD'
    assert c.supplier_id == ca.id and c.service_id == sv.id
    assert c.usage_label() == 'Signature' and c.support_label() == 'Carte à puce'
    assert c.duration_years == 3 and c.amount_ttc == 120.5
    assert c.revocation_code == 'SECRET-42'


def test_un_certificat_electronique_n_exige_pas_de_domaine(client):
    """…mais il exige un titulaire, et un certificat TLS exige un domaine :
    chacun a ce qui le désigne."""
    r = client.post('/certificates/create', data={
        'kind': 'signature', 'service_name': 'Parapheur',
        'expiry_date': _demain(90).isoformat()}, follow_redirects=True)
    assert 'titulaire est obligatoire' in r.get_data(as_text=True)
    assert Certificate.query.count() == 0

    r = client.post('/certificates/create', data={
        'kind': 'tls', 'service_name': 'Site', 'expiry_date': _demain(90).isoformat()},
        follow_redirects=True)
    assert 'domaine est obligatoire' in r.get_data(as_text=True)
    assert Certificate.query.count() == 0


def test_la_nature_ne_change_plus_apres_creation(client):
    """Basculer de l'une à l'autre laisserait un titulaire sur un certificat
    TLS, ou un domaine sur une carte à puce."""
    c = Certificate(kind='signature', service_name='Parapheur', holder='ARNAUD',
                    expiry_date=_demain(200))
    db.session.add(c)
    db.session.commit()
    client.post(f'/certificates/{c.id}/edit', data={
        'kind': 'tls', 'service_name': 'Parapheur', 'holder': 'ARNAUD',
        'domain': 'www.ville.fr', 'expiry_date': _demain(200).isoformat()},
        follow_redirects=True)
    db.session.expire(c)
    assert c.kind == 'signature'


# ── Ce qu'on a DÉCIDÉ, et ce que les dates disent ──

def test_un_certificat_revoque_sort_de_la_surveillance(client):
    """Il n'est déjà plus utilisable : sa date ne veut plus rien dire, et le
    rappeler chaque matin n'userait que l'attention. Un suspendu le
    redeviendra — son échéance continue de compter."""
    revoque = Certificate(kind='signature', service_name='A', holder='X',
                          expiry_date=_demain(2), validity='revoque')
    suspendu = Certificate(kind='signature', service_name='B', holder='Y',
                           expiry_date=_demain(2), validity='suspendu')
    db.session.add_all([revoque, suspendu])
    db.session.commit()
    assert revoque.monitored() is False and revoque.status() == 'success'
    assert suspendu.monitored() is True and suspendu.status() == 'danger'


def test_l_agenda_ignore_un_certificat_revoque(client):
    from app.dashboard import _agenda_items
    from app.models import User
    revoque = Certificate(kind='signature', service_name='Révoqué', holder='X',
                          expiry_date=_demain(10), validity='revoque')
    vivant = Certificate(kind='signature', service_name='Vivant', holder='Y',
                         expiry_date=_demain(10))
    db.session.add_all([revoque, vivant])
    db.session.commit()
    admin = User.query.filter_by(username='admin').first()
    _, echeances = _agenda_items(admin)
    noms = [i['name'] for i in echeances]
    assert any('Vivant' in n for n in noms)
    assert not any('Révoqué' in n for n in noms)


def test_la_lecture_tls_refuse_un_certificat_sans_domaine(client):
    """Sa date vient de l'autorité, pas d'une poignée de main réseau."""
    from app.certificates import refresh_certificate_tls
    c = Certificate(kind='signature', service_name='A', holder='X',
                    expiry_date=_demain(100))
    db.session.add(c)
    db.session.commit()
    ok, msg = refresh_certificate_tls(c, 'test')
    assert ok is False and "n'a pas de domaine" in msg


# ── Le code de révocation est un secret opératoire ──

def _cert_avec_code():
    c = Certificate(kind='signature', service_name='Parapheur', holder='ARNAUD',
                    expiry_date=_demain(300), revocation_code='SECRET-42')
    db.session.add(c)
    db.session.commit()
    return c


def test_le_code_de_revocation_est_rendu_a_qui_peut_modifier(client):
    """Masqué à l'écran jusqu'au geste qui le demande, mais bien transmis : il
    faut pouvoir le lire vite le jour où il sert."""
    c = _cert_avec_code()
    assert 'SECRET-42' in client.get(f'/certificates/{c.id}').get_data(as_text=True)


# Ce test n'utilise PAS la fixture `client` : elle ouvre une session admin, et
# Flask-Login memorise l'utilisateur courant sur `flask.g`, partage entre les
# requetes d'un meme test tant que le contexte applicatif reste pousse. Le
# lecteur y heriterait des droits de l'admin, et le test passerait pour de
# mauvaises raisons.
def test_le_code_de_revocation_n_est_pas_rendu_a_un_lecteur(app):
    from app.models import User
    c = _cert_avec_code()
    viewer = User(username='lecteur', email='l@ville.fr', role='viewer')
    viewer.set_password('Lecteur-2026!')
    db.session.add(viewer)
    db.session.commit()
    assert viewer.can_edit('certificates') is False

    lecteur = app.test_client()
    lecteur.post('/login', data={'username': 'lecteur', 'password': 'Lecteur-2026!'})
    html = lecteur.get(f'/certificates/{c.id}').get_data(as_text=True)
    # La fiche s'ouvre (lecture autorisée)…
    assert 'Parapheur' in html
    # …mais le secret n'y est pas : la garde est côté serveur, ne pas l'afficher
    # suffirait à qui sait lire une page HTML.
    assert 'SECRET-42' not in html


def test_un_champ_code_vide_n_efface_pas_le_secret(client):
    """Le formulaire ne réaffiche jamais le code : le renvoyer vide effacerait à
    chaque enregistrement un secret que personne n'a voulu retirer."""
    c = Certificate(kind='signature', service_name='Parapheur', holder='ARNAUD',
                    expiry_date=_demain(300), revocation_code='SECRET-42')
    db.session.add(c)
    db.session.commit()
    base = {'service_name': 'Parapheur', 'holder': 'ARNAUD',
            'expiry_date': _demain(300).isoformat()}
    client.post(f'/certificates/{c.id}/edit', data=dict(base, revocation_code=''),
                follow_redirects=True)
    db.session.expire(c)
    assert c.revocation_code == 'SECRET-42'

    # Le tiret l'efface explicitement.
    client.post(f'/certificates/{c.id}/edit', data=dict(base, revocation_code='-'),
                follow_redirects=True)
    db.session.expire(c)
    assert c.revocation_code is None


def test_le_code_ne_part_pas_dans_l_export_csv(client):
    """Un secret n'a pas à voyager dans un tableur qu'on s'envoie par mail."""
    c = Certificate(kind='signature', service_name='Parapheur', holder='ARNAUD',
                    expiry_date=_demain(300), revocation_code='SECRET-42')
    db.session.add(c)
    db.session.commit()
    csv = client.get('/data/certificates/export.csv').get_data(as_text=True)
    assert 'ARNAUD' in csv and 'SECRET-42' not in csv


def test_les_onglets_separent_les_deux_natures(client):
    db.session.add_all([
        Certificate(kind='tls', service_name='Site', domain='www.ville.fr',
                    expiry_date=_demain(100)),
        Certificate(kind='signature', service_name='Parapheur', holder='ARNAUD',
                    expiry_date=_demain(100)),
    ])
    db.session.commit()
    html = client.get('/certificates/?kind=signature').get_data(as_text=True)
    assert 'ARNAUD' in html and 'www.ville.fr' not in html
    html = client.get('/certificates/?kind=tls').get_data(as_text=True)
    assert 'www.ville.fr' in html and 'ARNAUD' not in html


def test_csv_transporte_les_deux_natures(client):
    """Un seul fichier pour les deux : une colonne `kind` les distingue, et les
    champs de l'autre restent vides. Une ligne sans `kind` reste un TLS — c'est
    ce que portent tous les fichiers exportés jusqu'ici."""
    from app import csv_io
    contenu = (
        'service_name;kind;domain;expiry_date;holder;civility;first_name;level\n'
        'Site;tls;www.ville.fr;2030-01-01;;;;\n'
        'Parapheur;signature;;2030-06-30;ARNAUD;mme;Claire;RGS**\n'
        'Ancien;;old.ville.fr;2030-03-01;;;;\n'
    ).encode('utf-8')
    created, errors = csv_io.import_csv('certificates', contenu)
    assert created == 3 and not errors
    sig = Certificate.query.filter_by(service_name='Parapheur').one()
    assert sig.kind == 'signature' and sig.holder_label() == 'Mme Claire ARNAUD'
    assert sig.level == 'RGS**'
    assert Certificate.query.filter_by(service_name='Ancien').one().kind == 'tls'
