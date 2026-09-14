"""Lecture du catalogue des applications chez SoftInventory.

SoftInventory DÉTIENT les applications : l'éditeur, le marché qui les couvre,
les pièces contractuelles, le volet RGPD, les référents. Sentinelle en tenait
une liste réduite, saisie une seconde fois. Ce module met fin au doublon.

── Ce qu'il rapatrie, et ce qu'il ne touche pas ──

L'IDENTITÉ de l'application : nom, description, responsable et son adresse,
hébergement, conteneurisation, URL, actif ou non.

Rien d'autre. Tout ce qui est PROPRE à Sentinelle — les mises à jour suivies,
les revues de droits, le contrat, les serveurs rattachés, le partage avec
Sesame — ne bouge jamais : c'est précisément ce qu'elle ajoute au catalogue, et
un import qui l'effacerait ne serait lancé qu'une fois.

── Rien n'est imposé ──

Sans URL ni clé, Sentinelle garde son catalogue local et se gère seule, comme
avant. L'import est un geste délibéré, déclenché depuis les Connecteurs.
"""
import logging

import requests
from flask import current_app

from app import db

logger = logging.getLogger(__name__)

# Au-delà, on renonce : un import ne doit pas suspendre l'écran indéfiniment.
DELAI_S = 10

# L'hébergement, dans les mots de Sentinelle. `hybride` compte comme SaaS : dès
# qu'une part est hébergée dehors, elle échappe au parc — c'est ce que le
# booléen veut dire ici.
_SAAS = {'saas', 'hybride'}


def _config():
    base = (current_app.config.get('SOFTINVENTORY_URL') or '').strip().rstrip('/')
    cle = current_app.config.get('SOFTINVENTORY_KEY') or ''
    return base, cle


def synchro_active():
    """Le connecteur est-il branche ? URL ET cle, les deux : une URL sans cle ne
    rapporte rien.

    Quand il l'est, le catalogue appartient a SoftInventory et ne se cree plus
    ici — une fiche saisie a la main pendant qu'une synchro tourne n'a pas
    d'avenir : soit elle double une application que l'import va reprendre, soit
    elle decrit un logiciel que SoftInventory ignore, et c'est la-bas qu'il faut
    le declarer.
    """
    base, cle = _config()
    return bool(base and cle)


def lire_catalogue():
    """Interroge `GET /api/v1/applications`.

    Renvoie `(applications, erreur)`. L'erreur est RENDUE, pas levée : un
    connecteur qui tombe doit produire un message lisible à l'écran — « clé
    refusée », « injoignable » — et non une page 500 où l'administrateur ne
    saura pas quoi corriger.
    """
    base, cle = _config()
    if not base or not cle:
        return [], "Connecteur non configuré : renseignez l'URL et la clé."

    try:
        r = requests.get(
            f'{base}/api/v1/applications',
            headers={'Authorization': f'Bearer {cle}', 'Accept': 'application/json'},
            timeout=DELAI_S,
        )
    except requests.RequestException as e:
        logger.warning('SoftInventory injoignable : %s', e)
        return [], f'SoftInventory injoignable à {base}. Vérifiez l\'URL et le réseau.'

    # Les codes que l'API pose volontairement, traduits dans les mots de
    # l'administrateur : « 401 » ne dit pas quoi faire, « la clé est refusée »
    # dit d'aller la régénérer.
    if r.status_code == 401:
        return [], 'Clé refusée par SoftInventory : régénérez-la dans ses Paramètres.'
    if r.status_code != 200:
        return [], f'SoftInventory a répondu {r.status_code}.'

    try:
        charge = r.json()
    except ValueError:
        return [], "Réponse illisible : l'URL pointe-t-elle bien sur SoftInventory ?"
    if not isinstance(charge, list):
        return [], 'Réponse inattendue : une liste d\'applications était attendue.'
    return charge, None


def _exploitable(a):
    """Une application utilisable : un identifiant et un nom.

    Une ligne invalide est ÉCARTÉE, pas fatale — un import qui échouerait en
    entier parce qu'une application sur cent n'a pas de nom serait inutilisable
    le jour où il sert le plus.
    """
    return (isinstance(a, dict)
            and isinstance(a.get('id'), int) and a['id'] >= 1
            and isinstance(a.get('name'), str) and a['name'].strip())


def _equipements_actifs():
    """Le parc, indexé par identifiant — la clé du rapprochement des serveurs."""
    from app.models import Equipment
    return {e.id: e for e in Equipment.query.filter_by(is_active=True).all()}


def _serveurs_voulus(a, equipements):
    """Les équipements de CE parc où l'application est installée.

    SoftInventory publie pour chaque serveur son `sentinelle_id` : l'identifiant
    de l'équipement ICI. C'est lui qui rapproche, jamais le nom — une machine
    renommée d'un côté reste la même des deux.

    Un serveur saisi là-bas que Sentinelle ne connaît pas porte `null`, et un
    équipement supprimé ici a disparu du parc : dans les deux cas le lien est
    ignoré. Poser une installation sur une machine qu'on ne sait pas nommer
    n'apprendrait rien à personne.
    """
    voulus = set()
    for s in a.get('servers') or []:
        if not isinstance(s, dict):
            continue
        eid = s.get('sentinelle_id')
        if isinstance(eid, int) and eid in equipements:
            voulus.add(eid)
    return voulus


def _etapes(charge):
    """Ce que l'import ferait, application par application, sans rien écrire.

    Le rapprochement se fait par IDENTIFIANT distant d'abord — il survit à un
    renommage —, par NOM ensuite : c'est ce qui permet aux fiches déjà saisies
    ici de retrouver leur jumelle au lieu d'en créer une doublon. Le nom ne
    rapproche que d'une fiche LIBRE, sans identifiant distant : sans cette
    garde, deux applications homonymes se voleraient la même fiche à chaque
    import.

    Le calcul est SÉPARÉ de l'écriture pour que l'écran puisse annoncer ligne
    par ligne ce qui va se passer, et laisser décocher. Il se rejoue au moment
    d'appliquer plutôt que de voyager jusqu'au navigateur : le catalogue a pu
    bouger entre les deux, et c'est l'état du moment qui fait foi.
    """
    from app.models import Software

    valides = [a for a in charge if _exploitable(a)]
    base = {'ecartes': len(charge) - len(valides), 'homonymes': [], 'conflits': []}

    existants = Software.query.all()
    par_id = {s.inventory_id: s for s in existants if s.inventory_id}
    par_nom = {(s.name or '').strip().lower(): s for s in existants}
    equipements = _equipements_actifs()

    etapes = []
    vus = set()

    for a in valides:
        nom = a['name'].strip()
        cle_nom = nom.lower()
        # Le catalogue peut porter deux applications de même nom ; ici le nom
        # sert de rapprochement, on garde la première et on nomme les autres.
        if cle_nom in vus:
            base['homonymes'].append(nom)
            continue
        vus.add(cle_nom)

        par_identifiant = par_id.get(a['id'])
        par_le_nom = par_nom.get(cle_nom)
        if not par_identifiant and par_le_nom and par_le_nom.inventory_id:
            base['conflits'].append(nom)
            continue

        sw = par_identifiant or par_le_nom
        # Une fiche ECARTEE s'annonce comme telle : l'ecran la presente decochee,
        # et la recocher la fait revenir avec tout ce qu'elle porte — mises a
        # jour suivies, revues de droits, contrat.
        if sw is not None and sw.excluded:
            action = 'ecarte'
        elif sw is None:
            action = 'creer'
        elif sw.origin == 'inventory':
            action = 'actualiser'
        else:
            action = 'adopter'

        # Les installations : ce que SoftInventory déclare, comparé à ce que la
        # fiche porte ici. Une fiche neuve part de rien, tout y est ajout.
        voulus = _serveurs_voulus(a, equipements)
        actuels = {e.id for e in sw.equipments} if sw is not None else set()
        etapes.append({
            'app': a,
            'sw': sw,
            'action': action,
            'nom': nom,
            'ajouts': sorted(voulus - actuels),
            'retraits': sorted(actuels - voulus),
            'equipements': equipements,
        })

    return etapes, base


def previsualiser():
    """Le plan, pour l'écran de comparaison : rien n'est écrit.

    Chaque application y est nommée avec ce qui lui arriverait, et les
    installations qui seraient posées ou retirées le sont aussi — c'est là que
    se joue l'arbitrage, une fiche pouvant très bien être à jour tandis que ses
    serveurs ne le sont pas.
    """
    charge, erreur = lire_catalogue()
    if erreur:
        return None, erreur

    etapes, base = _etapes(charge)
    equipements = _equipements_actifs()

    def _noms(ids):
        return [equipements[i].name for i in ids if i in equipements]

    lignes = [{
        'id': e['app']['id'],
        'nom': e['nom'],
        'action': e['action'],
        'ajouts': _noms(e['ajouts']),
        'retraits': _noms(e['retraits']),
    } for e in etapes]

    return {'lignes': lignes, **base}, None


def importer(selection=None, ecrire=True):
    """Verse le catalogue dans les fiches logiciel.

    `selection` porte les identifiants SoftInventory retenus dans l'écran de
    comparaison ; `None` vaut « tout », pour un appel qui ne passe pas par lui.
    Une application écartée n'est pas refusée pour toujours : elle reparaîtra au
    prochain import, cochée comme les autres.

    `ecrire=False` ne fait que compter : de quoi vérifier le tuyau sans rien
    changer.
    """
    charge, erreur = lire_catalogue()
    if erreur:
        return None, erreur

    etapes, base = _etapes(charge)
    retenus = None if selection is None else set(selection)

    rapport = {'crees': 0, 'adoptes': 0, 'actualises': 0, 'ecartes_fiches': 0,
               'reprises': 0, 'liens_poses': 0, 'liens_retires': 0, **base}

    from app.models import Software

    for e in etapes:
        a, sw = e['app'], e['sw']
        ecartee = sw is not None and sw.excluded

        # Sans selection (appel automatique), on respecte les refus deja pris et
        # on n'en prend aucun nouveau : un import qui tourne seul n'a pas a
        # decider ce qu'on garde.
        if retenus is None:
            if ecartee:
                rapport['ecartes_fiches'] += 1
                continue
        elif a['id'] not in retenus:
            # Decoche : la fiche est ECARTEE. Elle existe deja, ou on la cree
            # ecartee — c'est ainsi que le refus se retient d'un import a
            # l'autre. Ses champs ne sont pas actualises : on n'a pas a
            # rafraichir ce qu'on vient de mettre de cote.
            if ecrire:
                if sw is None:
                    sw = Software(name=e['nom'], origin='inventory',
                                  inventory_id=a['id'], excluded=True)
                    db.session.add(sw)
                else:
                    sw.excluded = True
            rapport['ecartes_fiches'] += 1
            continue

        if sw is None:
            sw = Software(name=e['nom'])
            if ecrire:
                db.session.add(sw)

        if ecrire:
            # Cochee : la fiche est (ou redevient) visible.
            sw.excluded = False
            sw.name = e['nom']
            sw.description = (a.get('description') or '')[:2000]
            sw.responsible = (a.get('responsible') or '')[:128]
            sw.responsible_email = (a.get('responsible_email') or '')[:120]
            sw.url = (a.get('url') or '')[:256]
            sw.is_saas = (a.get('hosting') or '') in _SAAS
            sw.is_docker = bool(a.get('containerized'))
            sw.is_active = bool(a.get('is_active', True))
            sw.origin = 'inventory'
            sw.inventory_id = a['id']

            # Les installations suivent le catalogue : SoftInventory tient le
            # lien logiciel/serveur, Sentinelle le recopie. Les deux sens sont
            # appliqués — poser sans retirer laisserait une machine mise hors
            # service porter éternellement ses applications.
            equipements = e['equipements']
            for eid in e['ajouts']:
                if eid in equipements:
                    sw.equipments.append(equipements[eid])
            for eid in e['retraits']:
                if eid in equipements:
                    sw.equipments.remove(equipements[eid])

        rapport['liens_poses'] += len(e['ajouts'])
        rapport['liens_retires'] += len(e['retraits'])
        if ecartee:
            rapport['reprises'] += 1
        elif e['action'] == 'creer':
            rapport['crees'] += 1
        elif e['action'] == 'actualiser':
            rapport['actualises'] += 1
        else:
            rapport['adoptes'] += 1

    if ecrire:
        db.session.commit()
        logger.info('Import du catalogue : %s', {k: (len(v) if isinstance(v, list) else v)
                                                 for k, v in rapport.items()})
    return rapport, None
