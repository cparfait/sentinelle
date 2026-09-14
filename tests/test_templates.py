"""Smoke de rendu Jinja : tous les templates HTML doivent compiler.

Detecte les erreurs de syntaxe Jinja (macros, blocs, imports) sans avoir
besoin de visiter chaque route.
"""


def test_tous_les_templates_compilent(app):
    templates = [t for t in app.jinja_env.list_templates() if t.endswith('.html')]
    assert templates, 'aucun template trouve'
    for t in templates:
        app.jinja_env.get_template(t)  # leve TemplateSyntaxError si invalide
