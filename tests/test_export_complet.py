"""L'export total de secours : une archive sur DISQUE, jamais en mémoire.

Le coût d'un export ne doit pas dépendre de ce qu'on a mis dedans. L'ancienne
version tenait le ZIP dans un `BytesIO` et lisait la base d'un bloc — sans
conséquence à quelques mégaoctets, un risque d'épuisement mémoire depuis que
les pièces jointes la font peser des centaines.
"""
import io
import zipfile

import pytest

from config import Config
from app import create_app, db
from app.models import Document, DocumentContent, Software


# La fixture `app` de conftest.py monte une base EN MEMOIRE : elle n'a pas de
# fichier, et l'export n'a donc rien a copier. Ces tests-ci veulent justement
# verifier la copie : ils montent une base sur DISQUE.
@pytest.fixture()
def app(tmp_path):
    class C(Config):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{tmp_path / "export.db"}'
        SECRET_KEY = 'x'
        TESTING = True
        WTF_CSRF_ENABLED = False
    application = create_app(C)
    with application.app_context():
        yield application
        db.session.remove()


@pytest.fixture()
def client(app):
    from app.models import User
    admin = User.query.filter_by(username='admin').first()
    admin.set_password('mdp-de-test')
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'mdp-de-test'})
    return c


def _archive(client, url='/data/export-full.zip'):
    r = client.get(url)
    assert r.status_code == 200, r.status_code
    return r, zipfile.ZipFile(io.BytesIO(r.data))


def test_l_archive_contient_la_base_et_les_csv(client):
    r, z = _archive(client)
    noms = z.namelist()
    assert 'base/sentinelle.db' in noms
    assert 'consultation.html' in noms and 'LISEZMOI.txt' in noms
    assert any(n.startswith('csv/') for n in noms)
    assert 'attachment' in r.headers['Content-Disposition']
    assert '.zip' in r.headers['Content-Disposition']


def test_la_base_exportee_est_lisible(client, tmp_path):
    """Une copie prise par l'API `backup` de SQLite, pas un `shutil.copy` :
    celui-ci donnerait un fichier incohérent sur une base en cours d'écriture,
    le journal WAL vivant à côté."""
    import sqlite3
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()

    _, z = _archive(client)
    chemin = tmp_path / 'copie.db'
    chemin.write_bytes(z.read('base/sentinelle.db'))
    c = sqlite3.connect(chemin)
    assert c.execute('SELECT name FROM software').fetchall() == [('GED',)]
    c.close()


def test_l_export_allege_laisse_les_fiches_et_retire_les_octets(client, tmp_path):
    """Une archive allégée ne remplace pas une complète : les fiches de
    documents y sont, leur contenu non — les téléchargements répondraient 404."""
    import sqlite3
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    doc = Document(software_id=sw.id, filename='acte.pdf', size=18)
    doc.content = DocumentContent(data=b'%PDF-1.4 acte signe')
    db.session.add(doc)
    db.session.commit()

    def _compte(url):
        _, z = _archive(client, url)
        chemin = tmp_path / ('c' + str(abs(hash(url))) + '.db')
        chemin.write_bytes(z.read('base/sentinelle.db'))
        c = sqlite3.connect(chemin)
        try:
            return (c.execute('SELECT count(*) FROM document').fetchone()[0],
                    c.execute('SELECT count(*) FROM document_content').fetchone()[0])
        finally:
            c.close()

    assert _compte('/data/export-full.zip') == (1, 1)
    assert _compte('/data/export-full.zip?sans_documents=1') == (1, 0)


def test_l_allegement_ne_touche_pas_la_base_vivante(client):
    """Le DELETE porte sur la COPIE. Exporter ne doit rien retirer à personne."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    doc = Document(software_id=sw.id, filename='acte.pdf', size=18)
    doc.content = DocumentContent(data=b'%PDF-1.4 acte signe')
    db.session.add(doc)
    db.session.commit()

    client.get('/data/export-full.zip?sans_documents=1')
    db.session.expire_all()
    assert DocumentContent.query.count() == 1
    assert client.get(f'/documents/{doc.id}/download').data == b'%PDF-1.4 acte signe'


def test_la_copie_de_travail_ne_reste_pas_a_cote_de_l_archive(client):
    """Une fois dans le ZIP, la copie de la base ne sert plus : la garder
    doublerait la place occupée le temps de l'envoi."""
    import os
    from app import full_export
    _, chemin = full_export.build_full_export(client.application)
    try:
        assert os.path.exists(chemin)
        assert not os.path.exists(os.path.join(os.path.dirname(chemin), 'sentinelle.db'))
    finally:
        import shutil
        shutil.rmtree(os.path.dirname(chemin), ignore_errors=True)


def test_les_restes_abandonnes_sont_balayes(client, monkeypatch):
    """La suppression après envoi est du meilleur effort : elle n'arrive pas si
    le client coupe ou si le process est tué. Un ZIP de plusieurs centaines de
    mégaoctets oublié à chaque fois finirait par remplir le disque."""
    import os
    import shutil
    import tempfile
    import time
    from app import full_export

    racine = tempfile.mkdtemp(prefix='racine-test-')
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: racine)
    try:
        vieux = os.path.join(racine, full_export._PREFIXE + 'abandonne')
        recent = os.path.join(racine, full_export._PREFIXE + 'en-cours')
        etranger = os.path.join(racine, 'autre-chose')
        for d in (vieux, recent, etranger):
            os.makedirs(d)
            open(os.path.join(d, 'archive.zip'), 'wb').write(b'x')
        # Le vieux date d'avant la péremption ; les deux autres non.
        ancien = time.time() - full_export._PEREMPTION_S - 60
        os.utime(vieux, (ancien, ancien))
        os.utime(etranger, (ancien, ancien))

        full_export._balayer_restes()

        assert not os.path.exists(vieux)          # emporté
        assert os.path.exists(recent)             # un export en cours est épargné
        assert os.path.exists(etranger)           # ce qui n'est pas à nous non plus
    finally:
        shutil.rmtree(racine, ignore_errors=True)


def test_reserve_aux_administrateurs(app):
    from app.models import User
    v = User(username='lecteur', email='l@v.fr', role='viewer')
    v.set_password('Lecteur-2026!')
    db.session.add(v)
    db.session.commit()
    lecteur = app.test_client()
    lecteur.post('/login', data={'username': 'lecteur', 'password': 'Lecteur-2026!'})
    r = lecteur.get('/data/export-full.zip', follow_redirects=False)
    assert r.status_code in (301, 302)
