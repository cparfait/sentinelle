"""La reconstruction de la table `certificate` sur une base ANCIENNE.

Le domaine d'un certificat a cessé d'être obligatoire — un certificat
électronique n'en a pas. SQLite ne sait pas relâcher un `NOT NULL` sur une table
existante : il faut la reconstruire. Le piège est qu'une base neuve naît au bon
schéma, et que le problème ne se voit donc QUE sur une base ancienne : ces tests
en fabriquent une.
"""
import sqlite3

import pytest

from config import Config
from app import create_app, db


@pytest.fixture()
def base_ancienne(tmp_path):
    """Une base au schéma d'avant : `certificate.domain` obligatoire, `kind` et
    `validity` ajoutés à chaud et donc NULL sur les lignes existantes."""
    chemin = tmp_path / 'ancienne.db'
    c = sqlite3.connect(chemin)
    c.executescript("""
        CREATE TABLE certificate (
            id INTEGER NOT NULL PRIMARY KEY,
            service_name VARCHAR(128) NOT NULL,
            domain VARCHAR(256) NOT NULL,
            issuer VARCHAR(128),
            equipment_id INTEGER,
            issued_at DATE,
            expiry_date DATE NOT NULL,
            auto_renew BOOLEAN,
            description TEXT,
            priority VARCHAR(20),
            is_active BOOLEAN,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE INDEX ix_certificate_equipment_id ON certificate (equipment_id);
        INSERT INTO certificate
            (id, service_name, domain, issuer, expiry_date, priority, is_active)
        VALUES (1, 'Site web', 'www.ville.fr', 'Let''s Encrypt', '2030-01-01', 'high', 1),
               (2, 'Intranet', 'intra.ville.fr', NULL, '2031-06-30', 'medium', 1);
    """)
    c.commit()
    c.close()
    return chemin


def _demarre(chemin):
    class C(Config):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{chemin}'
        SECRET_KEY = 'x'
        TESTING = True
    return create_app(C)


def _colonne(chemin, table, nom):
    c = sqlite3.connect(chemin)
    try:
        for r in c.execute(f'PRAGMA table_info({table})'):
            if r[1] == nom:
                return {'notnull': r[3]}
    finally:
        c.close()
    return None


def test_la_table_est_reconstruite_sans_perte(base_ancienne):
    _demarre(base_ancienne)
    # Le domaine n'est plus obligatoire…
    assert _colonne(base_ancienne, 'certificate', 'domain')['notnull'] == 0
    # …et rien n'a été perdu.
    c = sqlite3.connect(base_ancienne)
    lignes = dict(c.execute('SELECT id, domain FROM certificate'))
    assert lignes == {1: 'www.ville.fr', 2: 'intra.ville.fr'}
    # Les colonnes ajoutées à chaud sont comblées : la table reconstruite les
    # déclare NOT NULL, et la recopie aurait échoué sur la première ligne
    # d'avant.
    kinds = [r[0] for r in c.execute('SELECT kind FROM certificate')]
    assert kinds == ['tls', 'tls']
    assert [r[0] for r in c.execute('SELECT validity FROM certificate')] == \
        ['valide', 'valide']
    # La table de travail ne survit pas.
    noms = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'certificate%'")]
    assert 'certificate_ancien' not in noms
    c.close()


def test_un_certificat_electronique_s_insere_ensuite(base_ancienne):
    """Le but de tout ceci : sur une base ancienne, l'insertion échouait — et
    seulement là."""
    from datetime import date
    app = _demarre(base_ancienne)
    with app.app_context():
        from app.models import Certificate
        db.session.add(Certificate(kind='signature', service_name='Parapheur',
                                   holder='ARNAUD', expiry_date=date(2030, 1, 1)))
        db.session.commit()
        c = Certificate.query.filter_by(kind='signature').one()
        assert c.domain is None and c.label() == 'Parapheur - ARNAUD'


def test_un_second_demarrage_ne_refait_rien(base_ancienne):
    """La reconstruction se reconnaît terminée : relancer l'application ne doit
    pas rejouer une chirurgie de table à chaque démarrage."""
    _demarre(base_ancienne)
    c = sqlite3.connect(base_ancienne)
    avant = c.execute('SELECT count(*) FROM certificate').fetchone()[0]
    c.close()
    _demarre(base_ancienne)
    c = sqlite3.connect(base_ancienne)
    assert c.execute('SELECT count(*) FROM certificate').fetchone()[0] == avant
    c.close()


def test_une_reconstruction_interrompue_ne_perd_rien(base_ancienne):
    """Coupure de courant au milieu : la table neuve est vide, l'ancienne porte
    les données. On repart de l'ancienne — l'interruption ne doit rien coûter."""
    c = sqlite3.connect(base_ancienne)
    c.executescript("""
        ALTER TABLE certificate RENAME TO certificate_ancien;
        CREATE TABLE certificate (
            id INTEGER NOT NULL PRIMARY KEY,
            service_name VARCHAR(128) NOT NULL,
            domain VARCHAR(256),
            expiry_date DATE NOT NULL
        );
    """)
    c.commit()
    c.close()

    _demarre(base_ancienne)
    c = sqlite3.connect(base_ancienne)
    lignes = dict(c.execute('SELECT id, domain FROM certificate'))
    assert lignes == {1: 'www.ville.fr', 2: 'intra.ville.fr'}
    assert _colonne(base_ancienne, 'certificate', 'domain')['notnull'] == 0
    c.close()
