"""Recherche globale : les entités héritées de SoftInventory (logiciels, devis,
pièces jointes) doivent y être trouvées, et chacune respecte le droit de
lecture de sa catégorie."""
from app import db
from app.models import (Software, Supplier, Contract, Consultation, Quote,
                        Document, DocumentContent, Referential, Role, User)


def _client_pour(app, permissions):
    """Un client HTTP connecté avec un rôle aux droits donnés."""
    role = Role(name='restreint', permissions=permissions)
    db.session.add(role)
    db.session.commit()
    u = User(username='restreint', email='r@x.fr', role='restreint')
    u.set_password('Restreint-2026!')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'restreint', 'password': 'Restreint-2026!'})
    return c


def _rechercher(client, q):
    return client.get(f'/search?q={q}').get_data(as_text=True)


# ── Logiciels ──

def test_un_logiciel_se_trouve_par_son_nom_et_mene_a_sa_fiche(client):
    sw = Software(name='Genesis', version='4.2')
    db.session.add(sw)
    db.session.commit()
    html = _rechercher(client, 'genes')
    assert 'Genesis 4.2' in html
    assert f'/inventory/logiciels/{sw.id}' in html
    assert 'logiciel' in html


def test_un_logiciel_se_trouve_par_son_editeur_et_son_responsable(client):
    sup = Supplier(name='Berger-Levrault')
    db.session.add(sup)
    db.session.commit()
    db.session.add(Software(name='e.magnus', supplier_id=sup.id, responsible='Martine Dupuis'))
    db.session.commit()
    assert 'e.magnus' in _rechercher(client, 'berger')
    assert 'e.magnus' in _rechercher(client, 'dupuis')


def test_un_logiciel_a_la_corbeille_ne_se_trouve_pas(client):
    db.session.add(Software(name='Antique', is_active=False))
    db.session.commit()
    assert 'Antique' not in _rechercher(client, 'antiq')


# ── Devis ──

def test_un_devis_se_trouve_par_la_societe_et_mene_a_l_onglet_devis(client):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    cons = Consultation(software_id=sw.id, subject='Renouvellement 2026')
    db.session.add(cons)
    db.session.commit()
    db.session.add(Quote(consultation_id=cons.id, supplier_name='Docuware SAS', amount=12500))
    db.session.commit()
    html = _rechercher(client, 'docuware')
    assert 'Docuware SAS' in html and 'Renouvellement 2026' in html
    assert f'/inventory/logiciels/{sw.id}#devis' in html
    # ... et par l'objet de la consultation
    assert 'Docuware SAS' in _rechercher(client, 'renouvellement')


# ── Pièces jointes ──

def _piece(**parent):
    doc = Document(filename='acte-engagement.pdf', size=2048, **parent)
    doc.content = DocumentContent(data=b'%PDF-1.4')
    db.session.add(doc)
    db.session.commit()
    return doc


def test_une_piece_jointe_se_trouve_par_son_nom_et_mene_a_sa_fiche(client):
    ct = Contract(name='Marché GED')
    db.session.add(ct)
    db.session.commit()
    _piece(contract_id=ct.id)
    html = _rechercher(client, 'engagement')
    assert 'acte-engagement.pdf' in html
    assert 'Contrat Marché GED' in html
    assert f'/contracts/{ct.id}#documents' in html


def test_une_piece_jointe_se_trouve_par_sa_categorie(client):
    # Les catégories sont semées au démarrage : on prend celle qui existe.
    cat = Referential.query.filter_by(kind='doc_category', label='Délibération').first()
    assert cat is not None
    sw = Software(name='Paie')
    db.session.add(sw)
    db.session.commit()
    _piece(software_id=sw.id, category_id=cat.id)
    assert 'acte-engagement.pdf' in _rechercher(client, 'délib')


def test_une_piece_dont_la_fiche_est_a_la_corbeille_ne_se_trouve_pas(client):
    sw = Software(name='Vieux', is_active=False)
    db.session.add(sw)
    db.session.commit()
    _piece(software_id=sw.id)
    assert 'acte-engagement.pdf' not in _rechercher(client, 'engagement')


def test_les_pieces_jointes_disparaissent_quand_le_module_est_coupe(client, app):
    sw = Software(name='Paie')
    db.session.add(sw)
    db.session.commit()
    _piece(software_id=sw.id)
    assert 'acte-engagement.pdf' in _rechercher(client, 'engagement')
    app.config['DOCUMENTS_ENABLED'] = False
    assert 'acte-engagement.pdf' not in _rechercher(client, 'engagement')


# ── Droits ──

def test_sans_droit_inventaire_ni_logiciel_ni_sa_piece_mais_le_contrat_reste(app):
    sw = Software(name='Sésame')
    ct = Contract(name='Sésame maintenance')
    db.session.add_all([sw, ct])
    db.session.commit()
    _piece(software_id=sw.id)
    cons = Consultation(software_id=sw.id, subject='Sésame devis')
    db.session.add(cons)
    db.session.commit()
    db.session.add(Quote(consultation_id=cons.id, supplier_name='Sésame Éditions'))
    db.session.commit()

    c = _client_pour(app, {'inventory': 0, 'contracts': 1})
    html = _rechercher(c, 'sésame')
    assert 'Sésame maintenance' in html          # contrat : droit contracts
    assert 'Sésame Éditions' in html             # devis : droit contracts
    assert f'/inventory/logiciels/{sw.id}"' not in html   # logiciel : droit inventory
    assert 'acte-engagement.pdf' not in html     # sa pièce suit la fiche
