"""Les « pièces du marché » d'une base ancienne deviennent des documents du
contrat au démarrage : leurs fichiers rattachés au contrat avec catégorie,
date et montant ; sans fichier, un document qui attend l'acte."""
from datetime import date

from sqlalchemy import text

from app import db, _migrate_data
from app.models import Contract, Document, DocumentContent, Referential


def _base_ancienne():
    """Recrée ce qu'une base d'avant avait : la table contract_item et la
    colonne document.contract_item_id (le modèle ne les déclare plus)."""
    db.session.execute(text(
        "CREATE TABLE contract_item (id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL, "
        "label VARCHAR(128), kind VARCHAR(16), cost_yearly FLOAT, doc_date DATE, notes TEXT, "
        "created_at DATETIME)"))
    db.session.execute(text("ALTER TABLE document ADD COLUMN contract_item_id INTEGER"))
    db.session.commit()


def _piece(contract_id, label, kind='abonnement', cost=None, doc_date=None, notes=None):
    db.session.execute(text(
        "INSERT INTO contract_item (contract_id, label, kind, cost_yearly, doc_date, notes) "
        "VALUES (:c, :l, :k, :co, :d, :n)"),
        {'c': contract_id, 'l': label, 'k': kind, 'co': cost, 'd': doc_date, 'n': notes})
    db.session.commit()
    return db.session.execute(text("SELECT MAX(id) FROM contract_item")).scalar()


def _fichier(piece_id, nom):
    d = Document(filename=nom, size=12, uploaded_by='x')
    d.content = DocumentContent(data=b'%PDF-1.4 acte')
    db.session.add(d)
    db.session.commit()
    db.session.execute(text("UPDATE document SET contract_item_id=:p WHERE id=:d"),
                       {'p': piece_id, 'd': d.id})
    db.session.commit()
    return d


def test_une_piece_avec_fichiers_devient_des_documents_du_contrat(app):
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    _base_ancienne()
    p = _piece(ct.id, '50 postes', kind='perpetuelle', cost=4000, doc_date=date(2019, 2, 22),
               notes='lot 1')
    a = _fichier(p, 'marche-signe.pdf')
    b = _fichier(p, 'ar-electronique.pdf')
    _migrate_data()
    db.session.expire_all()
    a, b = db.session.get(Document, a.id), db.session.get(Document, b.id)
    assert a.contract_id == ct.id and b.contract_id == ct.id
    # La categorie vient de la nature ; « Licence perpétuelle » n existait pas
    # dans les categories, elle a ete creee.
    cat = Referential.query.filter_by(kind='doc_category', label='Licence perpétuelle').one()
    assert a.category_id == cat.id and b.category_id == cat.id
    assert a.doc_date == date(2019, 2, 22) and b.doc_date == date(2019, 2, 22)
    # Le montant une seule fois : sur le premier fichier.
    assert a.amount == 4000 and b.amount is None
    assert ct.documents_cost() == 4000
    assert a.notes == '50 postes — lot 1'
    # La ligne de piece est partie : rejouer ne recree rien.
    assert db.session.execute(text("SELECT COUNT(*) FROM contract_item")).scalar() == 0
    _migrate_data()
    assert Document.query.count() == 2


def test_une_piece_sans_fichier_devient_un_document_qui_attend_l_acte(app):
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    _base_ancienne()
    _piece(ct.id, 'Module paie', kind='abonnement', cost=1500, doc_date=date(2020, 1, 1))
    _piece(ct.id, None, kind='autre')
    _migrate_data()
    docs = ct.documents()
    assert len(docs) == 2
    paie = next(d for d in docs if d.filename == 'Module paie')
    assert not paie.has_file() and paie.amount == 1500 and paie.doc_date == date(2020, 1, 1)
    assert paie.category.label == 'Abonnement' and paie.uploaded_by == 'reprise'
    sans_nom = next(d for d in docs if d.filename != 'Module paie')
    assert sans_nom.filename == 'Autre' and sans_nom.category.label == 'Autre'
    assert db.session.execute(text("SELECT COUNT(*) FROM contract_item")).scalar() == 0
    _migrate_data()
    assert Document.query.count() == 2


def test_une_categorie_existante_n_est_pas_dupliquee(app):
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    _base_ancienne()
    _piece(ct.id, 'x', kind='autre')
    _piece(ct.id, 'y', kind='autre')
    _migrate_data()
    assert Referential.query.filter_by(kind='doc_category', label='Autre').count() == 1


def test_une_base_neuve_n_a_rien_a_migrer(app):
    ct = Contract(name='Marché RH')
    db.session.add(ct)
    db.session.commit()
    _migrate_data()          # pas de table contract_item : rien ne casse
    assert Document.query.count() == 0
