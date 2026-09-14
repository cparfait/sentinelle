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
        db.session.add(Software(name="GLPI", criticality=3, contract_id=None))
        db.session.commit()
    _importer(app, [_app(7, "GLPI")])
    with app.app_context():
        assert Software.query.one().criticality == 3


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


# ── Les serveurs d'installation ─────────────────────────────────────────────
# SoftInventory tient le lien logiciel/serveur ; Sentinelle le recopie sur ses
# équipements. Le rapprochement passe par `sentinelle_id`, jamais par le nom.


def _equipement(app, nom):
    from app.models import Equipment
    with app.app_context():
        e = Equipment(name=nom, kind="vm")
        db.session.add(e)
        db.session.commit()
        return e.id


def test_pose_les_installations_declarees_par_l_inventaire(app):
    eid = _equipement(app, "SRV-OPUS")
    _importer(app, [_app(1, "Concerto", servers=[
        {"id": 4, "name": "SRV-OPUS", "sentinelle_id": eid},
    ])])
    with app.app_context():
        sw = Software.query.one()
        assert [e.name for e in sw.equipments] == ["SRV-OPUS"]


def test_retire_une_installation_que_l_inventaire_ne_declare_plus(app):
    from app.models import Equipment
    eid = _equipement(app, "SRV-OPUS")
    with app.app_context():
        sw = Software(name="Concerto", inventory_id=1, origin="inventory")
        sw.equipments = [db.session.get(Equipment, eid)]
        db.session.add(sw)
        db.session.commit()
    # Le logiciel a été déplacé là-bas : le lien doit tomber ici aussi, sans
    # quoi une machine décommissionnée porterait ses applications à jamais.
    _importer(app, [_app(1, "Concerto", servers=[])])
    with app.app_context():
        assert Software.query.one().equipments == []


def test_ignore_un_serveur_que_sentinelle_ne_connait_pas(app):
    # Fiche serveur saisie dans SoftInventory (`sentinelle_id` nul), ou
    # équipement supprimé ici : rien où accrocher l'installation.
    _importer(app, [_app(1, "Concerto", servers=[
        {"id": 9, "name": "SRV-LOCAL", "sentinelle_id": None},
        {"id": 8, "name": "DISPARU", "sentinelle_id": 4242},
    ])])
    with app.app_context():
        assert Software.query.one().equipments == []


def test_ce_qui_est_decoche_est_ECARTE_donc_invisible(app):
    from app.inventory_sync import importer
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    charge = [_app(1, "Concerto"), _app(2, "GLPI")]
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge)):
        with app.app_context():
            rapport, _ = importer(selection=[1])
    assert rapport["crees"] == 1 and rapport["ecartes_fiches"] == 1
    with app.app_context():
        # La fiche ecartee EXISTE — c'est ainsi que le refus se retient — mais
        # elle est marquee, et toutes les lectures de l'application l'excluent.
        assert Software.query.filter_by(excluded=False).one().name == "Concerto"
        assert Software.query.filter_by(excluded=True).one().name == "GLPI"


def test_un_refus_tient_d_un_import_a_l_autre(app):
    from app.inventory_sync import importer, previsualiser
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    charge = [_app(1, "Concerto"), _app(2, "GLPI")]
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge)):
        with app.app_context():
            importer(selection=[1])
            # L'ecran la represente DECOCHEE : on n'a pas a redire non a chaque
            # import.
            plan, _ = previsualiser()
            assert [l["action"] for l in plan["lignes"] if l["nom"] == "GLPI"] == ["ecarte"]
            # Et un import automatique (sans selection) respecte le refus.
            rapport, _ = importer()
            assert rapport["ecartes_fiches"] == 1
            assert Software.query.filter_by(excluded=True).one().name == "GLPI"


def test_recocher_une_fiche_ecartee_la_fait_revenir(app):
    from app.inventory_sync import importer
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    charge = [_app(1, "Concerto"), _app(2, "GLPI")]
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge)):
        with app.app_context():
            importer(selection=[1])
            rapport, _ = importer(selection=[1, 2])
    assert rapport["reprises"] == 1
    with app.app_context():
        assert Software.query.filter_by(excluded=True).count() == 0
        assert {s.name for s in Software.query.all()} == {"Concerto", "GLPI"}


def test_la_previsualisation_annonce_sans_rien_ecrire(app):
    from app.inventory_sync import previsualiser
    eid = _equipement(app, "SRV-OPUS")
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    charge = [_app(1, "Concerto", servers=[
        {"id": 4, "name": "SRV-OPUS", "sentinelle_id": eid},
    ])]
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge)):
        with app.app_context():
            plan, erreur = previsualiser()
            assert erreur is None
            assert plan["lignes"] == [{
                "id": 1, "nom": "Concerto", "action": "creer",
                "ajouts": ["SRV-OPUS"], "retraits": [],
            }]
            # Rien n'a été écrit : c'est tout l'objet de l'écran.
            assert Software.query.count() == 0


def test_l_ecran_de_comparaison_precede_l_import(client, app):
    # Le bouton des Connecteurs mène à l'écran, pas à l'écriture : on voit ce
    # qui changerait avant que quoi que ce soit soit écrit.
    eid = _equipement(app, "SRV-OPUS")
    app.config["SOFTINVENTORY_URL"] = "http://inventaire.test"
    app.config["SOFTINVENTORY_KEY"] = "cle"
    charge = [_app(1, "Concerto", servers=[
        {"id": 4, "name": "SRV-OPUS", "sentinelle_id": eid},
    ])]
    with patch("app.inventory_sync.requests.get", return_value=_Reponse(charge)):
        r = client.post("/connecteurs/catalogue", data={"action": "preview"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Concerto" in html and "SRV-OPUS" in html
    with app.app_context():
        assert Software.query.count() == 0
