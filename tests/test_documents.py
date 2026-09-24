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
    assert Document(software_id=sw.id).permission_category() == 'software'
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

def test_un_pdf_s_affiche_sans_etre_enregistre(client):
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
    # La pièce s'ouvre dans un onglet à elle, plus dans un cadre de la fiche :
    # l'assouplissement en SAMEORIGIN / 'self' qu'exigeait ce cadre n'a plus
    # lieu d'être, et la garde revient au refus total.
    assert r.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']


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
    # La fiche propose alors le téléchargement, pas la lecture : son lien vise
    # /download et ne s'ouvre pas dans un onglet.
    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'guide.docx' in html
    assert f'/documents/{doc.id}/view' not in html
    assert f'/documents/{doc.id}/download' in html


def test_une_piece_lisible_s_ouvre_dans_un_onglet(client):
    """La pièce s'ouvrait dans une boîte modale ; elle prend maintenant un
    onglet a elle. Deux raisons : un acte scanné dans une fenêtre de 85 % de
    hauteur se lit à la loupe, et le navigateur apporte gratuitement sa propre
    visionneuse — zoom, recherche, impression, pagination.

    `rel="noopener"` va avec `target="_blank"` : sans lui, la page ouverte
    garde une poignée sur celle qui l'a ouverte (window.opener) et pourrait la
    faire naviguer ailleurs.
    """
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    _depose(client, 'software', sw.id, 'acte.pdf', b'%PDF-1.4 faux')
    doc = Document.query.one()

    html = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    lien = f'/documents/{doc.id}/view'
    assert lien in html
    debut = html.index(lien)
    balise = html[html.rindex('<a', 0, debut):html.index('>', debut) + 1]
    assert 'target="_blank"' in balise, balise
    assert 'rel="noopener"' in balise, balise

    # Et la page servie refuse tout encadrement : l'assouplissement qu'exigeait
    # le cadre d'autrefois n'a plus lieu d'etre.
    r = client.get(lien)
    assert r.status_code == 200
    assert r.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']


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


# ── La rétention des sauvegardes se règle dans l'application ──

def test_la_retention_se_regle_depuis_les_preferences(client, app):
    """C'est une politique, pas un paramètre de déploiement : la changer ne doit
    pas demander de redéployer la stack."""
    client.post('/preferences', data={'action': 'save_backup_keep',
                                      'backup_db_keep': '3'}, follow_redirects=True)
    assert app.config['BACKUP_DB_KEEP'] == 3
    # Elle survit à un rechargement : elle vit en base, pas en mémoire.
    from app import config_store
    config_store.load(app)
    assert app.config['BACKUP_DB_KEEP'] == 3


def test_la_retention_est_bornee_des_deux_cotes(client, app):
    """Zéro effacerait la sauvegarde à peine créée ; un chiffre sans limite
    remplirait le volume — une copie pèse ce que pèse la base."""
    for saisi, attendu in (('0', 1), ('999', 30), ('', 14), ('beaucoup', 14)):
        client.post('/preferences', data={'action': 'save_backup_keep',
                                          'backup_db_keep': saisi},
                    follow_redirects=True)
        assert app.config['BACKUP_DB_KEEP'] == attendu, saisi


def test_la_rotation_applique_le_reglage(client, app, tmp_path):
    """Le réglage doit VRAIMENT piloter la rotation, pas seulement s'afficher."""
    import os
    from app.db_backup import list_backups
    app.config['BACKUP_DB_DIR'] = str(tmp_path)
    app.config['BACKUP_DB_KEEP'] = 2
    # Une base en mémoire n'a pas de fichier à copier : on en fabrique une.
    for i in range(4):
        chemin = tmp_path / f'sentinelle_2026010{i}_120000.db'
        chemin.write_bytes(b'x')
        os.utime(chemin, (1000 + i, 1000 + i))
    assert len(list_backups(app)) == 4

    from app.db_backup import _rotate
    _rotate(app, str(tmp_path))
    assert len(list_backups(app)) == 2


def test_l_onglet_documents_d_un_logiciel_montre_les_pieces_de_ses_marches(client):
    """L'onglet restait vide alors que tout l'écrit existait : versé sous le
    marché ou sous le devis, là où il a été signé."""
    from app.documents import inherited_for_software
    from app.models import Consultation, Quote

    sw = Software(name='Concerto Opus')
    ct = Contract(name='Marché M20-23')
    db.session.add_all([sw, ct])
    db.session.commit()
    ct.software = [sw]
    cons = Consultation(software_id=sw.id, subject='Renouvellement 2027')
    db.session.add(cons)
    db.session.commit()
    devis = Quote(consultation_id=cons.id, supplier_name='Arpege')
    db.session.add(devis)
    db.session.commit()

    _depose(client, 'contract', ct.id, 'acte-signe.pdf')
    _depose(client, 'contract', ct.id, 'bon-de-commande.pdf')
    _depose(client, 'quote', devis.id, 'devis-2027.pdf')
    _depose(client, 'software', sw.id, 'guide.pdf')

    from flask import current_app
    with current_app.test_request_context():
        heritees = inherited_for_software(sw)
    assert {x['piece'].filename for x in heritees} == {
        'acte-signe.pdf', 'bon-de-commande.pdf', 'devis-2027.pdf'}
    # La pièce PROPRE à la fiche n'y est pas : elle vit déjà dans sa carte.
    origines = {x['piece'].filename: x['origine'] for x in heritees}
    assert origines['bon-de-commande.pdf'] == 'Marché M20-23'
    assert origines['devis-2027.pdf'].startswith('Devis Arpege —')

    # Et la fiche les montre : c'est là qu'on vient les chercher.
    page = client.get(f'/inventory/logiciels/{sw.id}').get_data(as_text=True)
    assert 'bon-de-commande.pdf' in page and 'devis-2027.pdf' in page


# ── Une pièce sans fichier : reprise sans son acte, elle l attend ──

def test_une_piece_sans_fichier_attend_son_acte(client):
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    piece = Document(contract_id=ct.id, filename='Bon de commande 2019', amount=1200,
                     notes='50 postes')
    db.session.add(piece)
    db.session.commit()
    assert not piece.has_file()
    # Ni téléchargement ni aperçu : il n y a rien derrière.
    assert client.get(f'/documents/{piece.id}/download').status_code == 404
    assert client.get(f'/documents/{piece.id}/view').status_code == 404
    html = client.get(f'/contracts/{ct.id}').get_data(as_text=True)
    assert 'fichier à déposer' in html and f'/documents/{piece.id}/file' in html
    # Le fichier arrive : la ligne le prend et garde ce qu elle savait.
    r = client.post(f'/documents/{piece.id}/file', data={'file': _fichier('bc-2019.pdf')},
                    content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(piece)
    assert piece.has_file() and piece.filename == 'bc-2019.pdf'
    assert piece.amount == 1200 and 'Bon de commande 2019' in piece.notes
    assert client.get(f'/documents/{piece.id}/download').data == b'%PDF-1.4 faux acte'
    # Une seconde fois : refusé, la pièce a déjà son fichier.
    r = client.post(f'/documents/{piece.id}/file', data={'file': _fichier('autre.pdf')},
                    content_type='multipart/form-data', follow_redirects=True)
    assert 'déjà son fichier' in r.get_data(as_text=True)


def test_apporter_un_fichier_demande_le_droit_d_ecriture(app):
    from app.models import User
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    piece = Document(contract_id=ct.id, filename='BC')
    lecteur = User(username='lecteur', email='l@v.fr', role='viewer')
    lecteur.set_password('Lecteur-2026!')
    db.session.add_all([piece, lecteur])
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'lecteur', 'password': 'Lecteur-2026!'})
    c.post(f'/documents/{piece.id}/file', data={'file': _fichier('bc.pdf')},
           content_type='multipart/form-data')
    db.session.refresh(piece)
    assert not piece.has_file()

