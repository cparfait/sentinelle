"""Les logiciels au tableau de bord, dans les badges de la barre latérale, dans
les listes par statut et dans le digest quotidien."""
from app import db
from app.models import Software, SystemUpdate


def _logiciel(name, **kw):
    sw = Software(name=name, **kw)
    db.session.add(sw)
    db.session.commit()
    return sw


def _maj_critique(sw):
    db.session.add(SystemUpdate(name=f'MAJ {sw.name}', status='critical', software_id=sw.id))
    db.session.commit()


def test_la_vignette_logiciels_compte_les_statuts(client):
    _logiciel('Sain')
    _logiciel('Fin de vie', lifecycle='fin_de_vie')
    _maj_critique(_logiciel('Critique'))
    html = client.get('/').get_data(as_text=True)
    assert 'Logiciels' in html
    assert '/inventory/logiciels/' in html
    # Les deux logiciels non verts sont dans « À traiter », avec leur motif.
    assert 'En fin de vie, successeur à trouver' in html
    assert 'Mise à jour critique en attente' in html
    assert 'Sain' not in html.split('À traiter')[1].split('</table>')[0]


def test_la_liste_par_statut_inclut_les_logiciels(client):
    sw = _logiciel('Ciril', lifecycle='fin_de_vie')
    html = client.get('/etat/warning').get_data(as_text=True)
    assert 'Ciril' in html and f'/inventory/logiciels/{sw.id}' in html
    assert 'Ciril' not in client.get('/etat/danger').get_data(as_text=True)


def test_le_badge_de_la_barre_laterale_compte_les_logiciels_critiques(client):
    _maj_critique(_logiciel('Critique'))
    _logiciel('Orange', lifecycle='fin_de_vie')   # orange : pas dans le badge
    html = client.get('/').get_data(as_text=True)
    # Le lien Logiciels de la barre latérale porte un badge « 1 ».
    bloc = html.split('href="/inventory/logiciels/"')[1].split('</a>')[0]
    assert 'badge bg-danger' in bloc and '>1<' in bloc


def test_le_badge_ignore_les_logiciels_en_pause(client):
    from app.snooze import set_snooze
    sw = _logiciel('Critique')
    _maj_critique(sw)
    set_snooze('software', sw.id, 7)
    html = client.get('/').get_data(as_text=True)
    bloc = html.split('href="/inventory/logiciels/"')[1].split('</a>')[0]
    assert 'badge bg-danger' not in bloc


def test_le_digest_a_une_rubrique_logiciels(app):
    from app.digest import build_daily_digest
    _logiciel('Sain')
    _logiciel('Ciril', lifecycle='fin_de_vie')
    _maj_critique(_logiciel('Paie'))
    subject, text, html, urgent = build_daily_digest('http://sentinelle.lan')
    assert urgent
    assert '== Logiciels ==' in text
    assert 'Ciril - En fin de vie' in text and 'Paie - Mise a jour critique' in text
    assert 'Sain' not in text
    assert 'http://sentinelle.lan/inventory/logiciels/' in html


def test_le_digest_respecte_le_report(app):
    from app.digest import build_daily_digest
    from app.snooze import set_snooze
    sw = _logiciel('Ciril', lifecycle='fin_de_vie')
    set_snooze('software', sw.id, 7)
    _subject, text, _html, urgent = build_daily_digest()
    assert not urgent and 'Ciril' not in text


def test_sans_droit_inventaire_pas_de_vignette_ni_d_urgence(app):
    from app.models import Role, User
    _logiciel('Ciril', lifecycle='fin_de_vie')
    role = Role(name='lecteur-comptes', permissions={'accounts': 1})
    db.session.add(role)
    db.session.commit()
    u = User(username='lc', email='lc@x.fr', role='lecteur-comptes')
    u.set_password('Lecteur-2026!')
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'lc', 'password': 'Lecteur-2026!'})
    html = c.get('/').get_data(as_text=True)
    assert 'Ciril' not in html
