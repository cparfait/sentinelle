"""Les logiciels et les fournisseurs ont leur propre catégorie de droits, et
les rôles existants héritent une fois du niveau qu'ils avaient sur
l'inventaire et sur les contrats."""
from app import db, _migrate_roles
from app.models import (Role, User, Software, Supplier, PERMISSION_CATEGORIES,
                        CATEGORY_LABELS)


def _client_pour(app, permissions, nom='r'):
    role = Role(name=nom, permissions=permissions)
    db.session.add(role)
    db.session.commit()
    u = User(username=nom, email=f'{nom}@x.fr', role=nom)
    u.set_password('Role-2026!')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': nom, 'password': 'Role-2026!'})
    return c


def test_les_deux_categories_existent_avec_leur_libelle():
    assert 'software' in PERMISSION_CATEGORIES and 'suppliers' in PERMISSION_CATEGORIES
    assert CATEGORY_LABELS['software'] == 'Logiciels' and CATEGORY_LABELS['suppliers'] == 'Fournisseurs'
    assert CATEGORY_LABELS['inventory'] == 'Matériel' and CATEGORY_LABELS['contracts'] == 'Contrats'


def test_la_migration_recopie_les_niveaux_une_seule_fois(app):
    ancien = Role(name='gestion-parc', permissions={'inventory': 2, 'contracts': 1})
    deja = Role(name='catalogue', permissions={'inventory': 3, 'software': 1, 'contracts': 0})
    sans = Role(name='comptes-seuls', permissions={'accounts': 3})
    db.session.add_all([ancien, deja, sans])
    db.session.commit()
    _migrate_roles()
    assert ancien.permissions['software'] == 2 and ancien.permissions['suppliers'] == 1
    assert deja.permissions['software'] == 1 and deja.permissions['suppliers'] == 0
    assert 'software' not in sans.permissions           # rien a copier : rien de pose
    # Idempotente : un niveau ajuste ensuite a la main n'est pas ecrase.
    ancien.permissions = {**ancien.permissions, 'software': 0}
    db.session.commit()
    _migrate_roles()
    assert ancien.permissions['software'] == 0


def test_les_roles_par_defaut_couvrent_les_nouvelles_categories(app):
    editor = Role.query.filter_by(name='editor').first()
    viewer = Role.query.filter_by(name='viewer').first()
    assert editor.permissions['software'] == 3 and editor.permissions['suppliers'] == 3
    assert viewer.permissions['software'] == 1 and viewer.permissions['suppliers'] == 1


def test_le_droit_logiciels_est_distinct_du_materiel(app):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    c = _client_pour(app, {'inventory': 3, 'software': 0}, 'parc')
    assert c.get('/inventory/').status_code == 200
    r = c.get('/inventory/logiciels/', follow_redirects=False)
    assert r.status_code == 302                                    # refuse, renvoye a l accueil
    assert c.get(f'/inventory/logiciels/{sw.id}').status_code == 302
    assert 'GED' not in c.get('/search?q=ged').get_data(as_text=True)
    html = c.get('/').get_data(as_text=True)
    assert 'href="/inventory/logiciels/"' not in html               # plus d entree dans le menu


def test_le_droit_fournisseurs_est_distinct_des_contrats(app):
    sup = Supplier(name='OVHcloud')
    db.session.add(sup)
    db.session.commit()
    c = _client_pour(app, {'contracts': 3, 'suppliers': 1}, 'marches')
    assert c.get('/contracts/').status_code == 200
    assert c.get(f'/suppliers/{sup.id}').status_code == 200        # lecture : oui
    r = c.post(f'/suppliers/{sup.id}/edit', data={'name': 'X'}, follow_redirects=False)
    assert r.status_code == 302 and Supplier.query.get(sup.id).name == 'OVHcloud'   # ecriture : non
    r = c.post('/suppliers/quick-create', data={'name': 'Nouveau'})
    assert Supplier.query.filter_by(name='Nouveau').first() is None


def test_lecture_seule_sur_les_logiciels_ne_permet_pas_de_creer(app):
    c = _client_pour(app, {'software': 1}, 'lecteur')
    assert c.get('/inventory/logiciels/').status_code == 200
    c.post('/inventory/logiciels/create', data={'name': 'Intrus', 'hosting': 'saas'})
    assert Software.query.filter_by(name='Intrus').first() is None
