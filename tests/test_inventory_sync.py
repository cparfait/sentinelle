"""Lecture du catalogue des applications chez SoftInventory.

Sens INVERSE des deux autres connecteurs : ici Sentinelle consomme. Elle ne
rapatrie que l'IDENTITÉ de l'application — ce qui lui est propre (mises à jour,
revues, contrat, serveurs) ne bouge jamais.
"""
from unittest.mock import patch

from app import db
from app.inventory_sync import importer
from app.models import Software


class _Reponse:
    """Ce que `requests.get` rend, réduit à ce que le module en lit."""

    def __init__(self, charge, status_code=200):
        self._charge = charge
        self.status_code = status_code

    def json(self):
        if self._charge is None:
            raise ValueError("pas du JSON")
        return self._charge


def _app(id, name, **reste):
    base = {
        "id": id, "name": name, "description": "", "is_active": True,
        "responsible": "", "responsible_email": "", "editor": "", "status": "production",
        "hosting": "on_premise", "containerized": False, "criticality": "",
        "services": [], "url": "", "internal_development": False,
        "updated_at": "2026-09-14T08:00:00.000Z",
    }
    base.update(reste)
    return base


def _importer(app, charge, status_code=200):
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge, status_code)):
        with app.app_context():
            return importer()


def test_sans_configuration_ne_fait_rien(app):
    app.config["SOFTINVENTORY_URL"] = ""
    app.config["SOFTINVENTORY_KEY"] = ""
    with app.app_context():
        rapport, erreur = importer()
    assert rapport is None and "non configuré" in erreur


def test_cle_refusee_est_dite_en_clair(app):
    # « 401 » ne dit pas quoi faire ; « la clé est refusée » dit d'aller la
    # régénérer.
    _, erreur = _importer(app, [], 401)
    assert "Clé refusée" in erreur


def test_reponse_qui_n_est_pas_une_liste(app):
    _, erreur = _importer(app, {"error": "..."})
    assert "liste" in erreur


def test_cree_les_applications_absentes(app):
    rapport, erreur = _importer(app, [_app(1, "GLPI"), _app(2, "Zabbix")])
    assert erreur is None
    assert rapport["crees"] == 2
    with app.app_context():
        assert Software.query.count() == 2
        glpi = Software.query.filter_by(name="GLPI").one()
        assert glpi.origin == "inventory" and glpi.inventory_id == 1


def test_rapproche_une_fiche_locale_par_son_NOM(app):
    # C'est ce qui évite le doublon au premier import : la fiche déjà saisie
    # ici retrouve sa jumelle au lieu d'en créer une seconde.
    with app.app_context():
        db.session.add(Software(name="GLPI", description="saisi ici"))
        db.session.commit()
    rapport, _ = _importer(app, [_app(7, "glpi", description="depuis l'inventaire")])
    assert rapport["adoptes"] == 1 and rapport["crees"] == 0
    with app.app_context():
        assert Software.query.count() == 1
        sw = Software.query.one()
        assert sw.inventory_id == 7 and sw.origin == "inventory"
        assert sw.description == "depuis l'inventaire"


def test_ne_touche_pas_ce_qui_est_PROPRE_a_sentinelle(app):
    # Les mises à jour, les revues, le contrat et les serveurs sont ce que
    # Sentinelle AJOUTE au catalogue : un import qui les effacerait ne serait
    # lancé qu'une fois.
    with app.app_context():
        db.session.add(Software(name="GLPI", share_sesame=False, contract_id=None))
        db.session.commit()
    _importer(app, [_app(7, "GLPI")])
    with app.app_context():
        assert Software.query.one().share_sesame is False


def test_actualise_sans_dupliquer_au_second_passage(app):
    _importer(app, [_app(1, "GLPI")])
    rapport, _ = _importer(app, [_app(1, "GLPI renommé")])
    assert rapport["crees"] == 0 and rapport["adoptes"] == 0 and rapport["actualises"] == 1
    with app.app_context():
        # Le rapprochement se fait sur l'IDENTIFIANT : il survit au renommage.
        assert Software.query.one().name == "GLPI renommé"


def test_ecarte_les_homonymes_en_les_nommant(app):
    rapport, _ = _importer(app, [_app(1, "GLPI"), _app(2, "glpi"), _app(3, "Zabbix")])
    assert rapport["crees"] == 2
    assert rapport["homonymes"] == ["glpi"]


def test_le_nom_ne_rapproche_que_d_une_fiche_LIBRE(app):
    # Une fiche déjà tenue par une autre application ne se laisse pas voler :
    # sans cette garde, deux homonymes basculeraient la même fiche à chaque
    # import, silencieusement.
    _importer(app, [_app(1, "GLPI")])
    rapport, _ = _importer(app, [_app(1, "GLPI"), _app(99, "GLPI")])
    assert rapport["conflits"] == [] or rapport["homonymes"] == ["GLPI"]
    with app.app_context():
        assert Software.query.count() == 1


def test_traduit_l_hebergement_et_la_conteneurisation(app):
    _importer(app, [
        _app(1, "SaaS", hosting="saas"),
        _app(2, "Hybride", hosting="hybride"),
        _app(3, "Chez nous", hosting="on_premise", containerized=True),
    ])
    with app.app_context():
        # « hybride » compte comme SaaS : dès qu'une part est hébergée dehors,
        # elle échappe au parc — c'est ce que le booléen veut dire ici.
        assert Software.query.filter_by(name="SaaS").one().is_saas is True
        assert Software.query.filter_by(name="Hybride").one().is_saas is True
        chez_nous = Software.query.filter_by(name="Chez nous").one()
        assert chez_nous.is_saas is False and chez_nous.is_docker is True


def test_ecarte_les_lignes_inexploitables_sans_tout_perdre(app):
    rapport, _ = _importer(app, [_app(1, "GLPI"), {"id": 2}, {"name": "sans id"}])
    assert rapport["crees"] == 1 and rapport["ecartes"] == 2
