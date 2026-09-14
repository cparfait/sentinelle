"""Couleur principale personnalisable (Preferences -> Apparence)."""
from app.theming import color_mix, normalize_color, primary_css_override


def test_normalize_color():
    assert normalize_color('#AB12ef') == '#ab12ef'
    assert normalize_color('  #123456 ') == '#123456'
    assert normalize_color('') == ''
    assert normalize_color('#12345') == ''
    assert normalize_color('rouge') == ''
    assert normalize_color('#12345g') == ''


def test_color_mix():
    assert color_mix('#000000', 0.5) == '#808080'
    assert color_mix('#ffffff', -0.5) == '#808080'
    assert color_mix('#4f46e5', 0) == '#4f46e5'


def test_css_override_vide_par_defaut():
    assert primary_css_override('') == ''
    assert primary_css_override('pas-une-couleur') == ''


def test_css_override_contient_les_variables():
    css = primary_css_override('#0d9488')
    assert '--primary:#0d9488' in css
    assert '--primary-dark:' in css
    assert '--primary-rgb:13,148,136' in css
    assert 'data-theme="dark"' in css


def test_logo_teinte(app, client):
    # Sans couleur : le SVG d'origine (degrade indigo).
    body = client.get('/logo.svg').data.decode('utf-8')
    assert '#6366f1' in body and '#3b82f6' in body

    app.config['UI_PRIMARY_COLOR'] = '#0d9488'
    body = client.get('/logo.svg').data.decode('utf-8')
    assert '#0d9488' in body
    assert '#6366f1' not in body and '#3b82f6' not in body


def test_css_override_fond_login():
    css = primary_css_override('#0d9488')
    assert '.login-container{background:linear-gradient(135deg,' in css


def test_base_html_sans_couleur(client):
    body = client.get('/preferences').data.decode('utf-8')
    assert '--primary:#' not in body  # pas de surcharge par defaut


def test_enregistrement_et_application(app, client):
    resp = client.post('/preferences', data={
        'action': 'save_ui_color', 'ui_color_enabled': 'on',
        'ui_primary_color': '#0D9488'}, follow_redirects=True)
    assert resp.status_code == 200
    assert app.config['UI_PRIMARY_COLOR'] == '#0d9488'
    body = client.get('/preferences').data.decode('utf-8')
    assert '--primary:#0d9488' in body

    # Couleur invalide -> refusee, la config ne bouge pas.
    client.post('/preferences', data={
        'action': 'save_ui_color', 'ui_color_enabled': 'on',
        'ui_primary_color': 'vert'}, follow_redirects=True)
    assert app.config['UI_PRIMARY_COLOR'] == '#0d9488'

    # Case decochee -> retour a la palette d'origine.
    client.post('/preferences', data={'action': 'save_ui_color'},
                follow_redirects=True)
    assert app.config['UI_PRIMARY_COLOR'] == ''
