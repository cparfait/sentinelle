"""Les logiciels pèsent dans le score de conformité globale, comme une
catégorie à part entière, sans se mêler aux catégories des webhooks."""
from app import db
from app.models import Software, CONFORMITY_CATEGORIES, WEBHOOK_CATEGORIES, CONFORMITY_LABELS
from app.app_settings import get_conformity_categories, set_conformity_categories


def test_les_logiciels_comptent_par_defaut_et_ont_leur_libelle(app):
    assert 'software' in CONFORMITY_CATEGORIES
    assert 'software' in get_conformity_categories()
    assert CONFORMITY_LABELS['software'] == 'Logiciels' and CONFORMITY_LABELS['inventory'] == 'Matériel'
    # Les webhooks s'abonnent aux categories de droits : pas de « software » la.
    assert 'software' not in WEBHOOK_CATEGORIES and 'inventory' in WEBHOOK_CATEGORIES


def test_le_score_compte_les_logiciels(client, app):
    db.session.add_all([Software(name='Sain'), Software(name='Fin de vie', lifecycle='fin_de_vie')])
    db.session.commit()
    set_conformity_categories(['software'])
    html = client.get('/').get_data(as_text=True)
    assert '1 OK sur 2 éléments suivis' in html
    # Décoché, le score les ignore ; la vignette reste.
    set_conformity_categories(['accounts'])
    html = client.get('/').get_data(as_text=True)
    assert '1 OK sur 2 éléments suivis' not in html and 'Logiciels' in html


def test_la_rubrique_conformite_propose_les_logiciels(client):
    html = client.get('/preferences').get_data(as_text=True)
    assert 'value="software"' in html and 'Logiciels' in html
    client.post('/preferences', data={'action': 'save_conformity', 'conformity': ['software']},
                follow_redirects=True)
    assert get_conformity_categories() == ['software']
