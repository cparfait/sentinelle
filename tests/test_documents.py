"""Pièces jointes : le fichier qui atteste ce que la fiche affirme.

Les octets vivent en base, dans une table à part ; le téléchargement se fait par
identifiant, jamais par un chemin venu du client."""
import io

from app import db
from app.models import (Document, DocumentContent, Software, Supplier, Contract,
                        Certificate)


def _fichier(nom, contenu=b'%PDF-1.4 faux acte'):
    return (io.BytesIO(contenu), nom)


def _depose(client, kind, parent_id, nom='marche.pdf', contenu=b'%PDF-1.4 faux acte'):
    return client.post('/documents/upload', data={
        'parent_kind': kind, 'parent_id': str(parent_id),
        'file': _fichier(nom, contenu)},
        content_type='multipart/form-data', follow_redirects=True)


def test_depot_et_telechargement(client):
    ct = Contract(name='Marché UGAP')
    db.session.add(ct)
    db.session.commit()
    _depose(client, 'contract', ct.id, 'marche-signe.pdf', b'%PDF-1.4 acte signe')

    doc = Document.query.one()
    assert doc.contract_id == ct.id and doc.filename == 'marche-signe.pdf'
    assert doc.size == len(b'%PDF-1.4 acte signe')
    assert doc.uploaded_by == 'admin'
    # Les octets vivent à part : la ligne se lit sans jamais les charger.
    assert doc.content.data == b'%PDF-1.4 acte signe'

    r = client.get(f'/documents/{doc.id}/download')
    assert r.status_code == 200
    assert r.data == b'%PDF-1.4 acte signe'
    # Toujours en pièce jointe, et jamais avec le type annoncé par le déposant.
    assert r.mimetype == 'application/octet-stream'
    assert 'attachment' in r.headers['Content-Disposition']


def test_un_html_ne_peut_pas_s_executer_sur_l_origine(client):
    """Déposé, il ne l'est pas : le type n'est pas dans la liste. Et s'il l'était,
    il partirait en pièce jointe — jamais rendu dans la page."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    r = _depose(client, 'software', sw.id, 'piege.html', b'<script>alert(1)</script>')
    assert 'non accept' in r.get_data(as_text=True)
    assert Document.query.count() == 0


def test_le_nom_de_fichier_est_nettoye(client):
    """Aucun chemin n'est accepté du client : ni traversée de répertoire, ni
    séparateur — le nom ne sert qu'à nommer la copie que le navigateur
    enregistre."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, '../../etc/passwd.pdf')
    doc = Document.query.one()
    assert '/' not in doc.filename and '\\' not in doc.filename
    assert '..' not in doc.filename


def test_un_fichier_trop_gros_est_refuse(client, app):
    app.config['DOCUMENT_MAX_MB'] = 1
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    r = _depose(client, 'software', sw.id, 'gros.pdf', b'x' * (2 * 1024 * 1024))
    assert 'trop volumineux' in r.get_data(as_text=True)
    assert Document.query.count() == 0


def test_un_fichier_vide_est_refuse(client):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    r = _depose(client, 'software', sw.id, 'vide.pdf', b'')
    assert 'vide' in r.get_data(as_text=True)
    assert Document.query.count() == 0


def test_la_suppression_emporte_les_octets(client):
    sup = Supplier(name='Berger-Levrault')
    db.session.add(sup)
    db.session.commit()
    _depose(client, 'supplier', sup.id, 'guide.pdf')
    doc = Document.query.one()
    client.post(f'/documents/{doc.id}/delete', follow_redirects=True)
    assert Document.query.count() == 0
    from app.models import DocumentContent
    assert DocumentContent.query.count() == 0


# ── Les droits suivent la fiche portante ──

def test_la_piece_herite_de_la_categorie_de_sa_fiche(client):
    """Lire un marché et lire ses pièces sont la même permission : une pièce ne
    se range pas dans une catégorie à elle."""
    sw = Software(name='GED')
    ct = Contract(name='Marché')
    cert = Certificate(kind='signature', service_name='Parapheur', holder='A',
                       expiry_date=__import__('datetime').date(2030, 1, 1))
    db.session.add_all([sw, ct, cert])
    db.session.commit()
    assert Document(software_id=sw.id).permission_category() == 'inventory'
    assert Document(contract_id=ct.id).permission_category() == 'contracts'
    assert Document(certificate_id=cert.id).permission_category() == 'certificates'
    # Sans parent identifiable, on retombe sur la plus restrictive plutôt que
    # sur la plus permissive.
    assert Document().permission_category() == 'contracts'


def test_un_lecteur_ne_peut_pas_deposer(app):
    # Sans la fixture `client` : elle ouvre une session admin, et Flask-Login
    # memorise l'utilisateur courant sur `flask.g`, partage entre les requetes
    # d'un meme test tant que le contexte applicatif reste pousse.
    from app.models import User
    sw = Software(name='GED')
    viewer = User(username='lecteur', email='l@v.fr', role='viewer')
    viewer.set_password('Lecteur-2026!')
    db.session.add_all([sw, viewer])
    db.session.commit()
    lecteur = app.test_client()
    lecteur.post('/login', data={'username': 'lecteur', 'password': 'Lecteur-2026!'})
    r = _depose(lecteur, 'software', sw.id)
    # L'apostrophe est echappee par Jinja dans le message flash : on cherche la
    # partie qui ne l'est pas.
    assert 'pas les droits pour déposer' in r.get_data(as_text=True)
    assert Document.query.count() == 0


# ── Le module s'active depuis les Préférences ──

def test_desactive_le_module_ferme_les_routes(client, app):
    """Désactivé, il ne se voit nulle part — et les fichiers déjà déposés
    restent en base plutôt que d'être perdus."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id)
    doc = Document.query.one()

    app.config['DOCUMENTS_ENABLED'] = False
    assert client.get(f'/documents/{doc.id}/download').status_code == 404
    assert client.post('/documents/upload', data={
        'parent_kind': 'software', 'parent_id': str(sw.id),
        'file': _fichier('x.pdf')}, content_type='multipart/form-data').status_code == 404
    # La fiche ne montre plus la carte…
    assert 'Pièces jointes' not in client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    # …mais la pièce est toujours là.
    assert Document.query.count() == 1


def test_le_reglage_se_change_depuis_les_preferences(client, app):
    client.post('/preferences', data={'action': 'save_documents',
                                      'documents_enabled': 'on',
                                      'document_max_mb': '25'}, follow_redirects=True)
    assert app.config['DOCUMENTS_ENABLED'] is True
    assert app.config['DOCUMENT_MAX_MB'] == 25

    # Le plafond est borné des deux côtés : zéro rendrait tout dépôt impossible
    # sans le dire, et un chiffre sans limite ferait de la base un partage.
    client.post('/preferences', data={'action': 'save_documents',
                                      'document_max_mb': '0'}, follow_redirects=True)
    assert app.config['DOCUMENTS_ENABLED'] is False
    assert app.config['DOCUMENT_MAX_MB'] == 1


# ── L'aperçu dans la page ──

def test_un_pdf_s_affiche_dans_la_page(client):
    """Un acte se lit ; l'enregistrer d'abord est un détour."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, 'marche.pdf', b'%PDF-1.4 acte')
    doc = Document.query.one()

    r = client.get(f'/documents/{doc.id}/view')
    assert r.status_code == 200
    assert r.data == b'%PDF-1.4 acte'
    assert r.mimetype == 'application/pdf'
    assert 'inline' in r.headers['Content-Disposition']
    # Les trois en-têtes de garde.
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    # SAMEORIGIN REMPLACE le DENY posé partout ailleurs : sans lui le cadre
    # resterait vide, DENY refusant l'encadrement même par soi-même.
    assert r.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert "frame-ancestors 'self'" in r.headers['Content-Security-Policy']


def test_un_svg_se_telecharge_mais_ne_s_affiche_jamais(client):
    """C'est du XML qui peut porter des scripts : le rendre sur notre origine
    l'exécuterait avec la session de qui l'ouvre."""
    from app.documents import viewable
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, 'logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    doc = Document.query.one()          # le dépôt, lui, est accepté
    assert viewable(doc) is False
    assert client.get(f'/documents/{doc.id}/view').status_code == 404
    assert client.get(f'/documents/{doc.id}/download').status_code == 200


def test_un_bureautique_n_a_pas_d_apercu(client):
    from app.documents import viewable
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, 'guide.docx', b'PK fauxdocx')
    doc = Document.query.one()
    assert viewable(doc) is False
    assert client.get(f'/documents/{doc.id}/view').status_code == 404
    # La fiche propose alors le téléchargement, pas l'aperçu : le lien du
    # fichier ne porte pas la classe (le script du cadre, lui, la mentionne —
    # on cherche donc l'attribut, pas le mot).
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'class="js-apercu"' not in html
    assert 'guide.docx' in html


def test_le_type_vient_de_l_extension_pas_du_deposant(client):
    """Le navigateur annonce ce qu'il veut à l'envoi ; on ne le croit pas."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    client.post('/documents/upload', data={
        'parent_kind': 'software', 'parent_id': str(sw.id),
        'file': (io.BytesIO(b'%PDF-1.4'), 'acte.pdf', 'text/html')},
        content_type='multipart/form-data', follow_redirects=True)
    doc = Document.query.one()
    assert doc.mime == 'text/html'                       # ce qu'il a annoncé
    r = client.get(f'/documents/{doc.id}/view')
    assert r.mimetype == 'application/pdf'               # ce qu'on renvoie


def test_l_apercu_se_coupe_depuis_les_preferences(client, app):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, 'marche.pdf')
    doc = Document.query.one()
    assert client.get(f'/documents/{doc.id}/view').status_code == 200

    client.post('/preferences', data={'action': 'save_documents',
                                      'documents_enabled': 'on',
                                      'document_max_mb': '10'},
                follow_redirects=True)      # case « aperçu » décochée
    assert app.config['DOCUMENT_INLINE_VIEW'] is False
    assert client.get(f'/documents/{doc.id}/view').status_code == 404
    # Le téléchargement, lui, reste.
    assert client.get(f'/documents/{doc.id}/download').status_code == 200


def test_l_apercu_respecte_les_droits_de_la_fiche(app):
    from app.models import User, Role
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    doc = Document(software_id=sw.id, filename='acte.pdf', size=8)
    doc.content = DocumentContent(data=b'%PDF-1.4')
    db.session.add(doc)
    # Un rôle sans aucun droit sur l'inventaire.
    aveugle = Role(name='aveugle', permissions={'inventory': 0})
    db.session.add(aveugle)
    db.session.commit()
    u = User(username='aveugle', email='a@v.fr', role='aveugle')
    u.set_password('Aveugle-2026!')
    db.session.add(u)
    db.session.commit()

    c = app.test_client()
    c.post('/login', data={'username': 'aveugle', 'password': 'Aveugle-2026!'})
    assert c.get(f'/documents/{doc.id}/view').status_code == 403
