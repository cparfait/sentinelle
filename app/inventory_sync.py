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


def importer(ecrire=True):
    """Verse le catalogue dans les fiches logiciel.

    Rapprochement par IDENTIFIANT distant d'abord — il survit à un renommage —,
    par NOM ensuite : c'est ce qui permet aux fiches déjà saisies ici de
    retrouver leur jumelle au lieu d'en créer une doublon. Le nom ne rapproche
    que d'une fiche LIBRE, sans identifiant distant : sans cette garde, deux
    applications homonymes se voleraient la même fiche à chaque import.

    `ecrire=False` ne fait que compter : de quoi vérifier le tuyau sans rien
    changer.
    """
    from app.models import Software

    charge, erreur = lire_catalogue()
    if erreur:
        return None, erreur

    valides = [a for a in charge if _exploitable(a)]
    rapport = {'crees': 0, 'adoptes': 0, 'actualises': 0,
               'ecartes': len(charge) - len(valides), 'homonymes': [], 'conflits': []}

    existants = Software.query.all()
    par_id = {s.inventory_id: s for s in existants if s.inventory_id}
    par_nom = {(s.name or '').strip().lower(): s for s in existants}
    vus = set()

    for a in valides:
        nom = a['name'].strip()
        cle_nom = nom.lower()
        # Le catalogue peut porter deux applications de même nom ; ici le nom
        # sert de rapprochement, on garde la première et on nomme les autres.
        if cle_nom in vus:
            rapport['homonymes'].append(nom)
            continue
        vus.add(cle_nom)

        par_identifiant = par_id.get(a['id'])
        par_le_nom = par_nom.get(cle_nom)
        if not par_identifiant and par_le_nom and par_le_nom.inventory_id:
            rapport['conflits'].append(nom)
            continue

        sw = par_identifiant or par_le_nom
        neuf = sw is None
        # L'origine est lue AVANT d'etre ecrasee : c'est elle qui distingue une
        # fiche deja refletee (actualisee) d'une fiche locale qu'on adopte.
        origine_avant = None if neuf else sw.origin
        if neuf:
            sw = Software(name=nom)
            if ecrire:
                db.session.add(sw)

        if ecrire:
            sw.name = nom
            sw.description = (a.get('description') or '')[:2000]
            sw.responsible = (a.get('responsible') or '')[:128]
            sw.responsible_email = (a.get('responsible_email') or '')[:120]
            sw.url = (a.get('url') or '')[:256]
            sw.is_saas = (a.get('hosting') or '') in _SAAS
            sw.is_docker = bool(a.get('containerized'))
            sw.is_active = bool(a.get('is_active', True))
            sw.origin = 'inventory'
            sw.inventory_id = a['id']

        if neuf:
            rapport['crees'] += 1
        elif origine_avant == 'inventory':
            rapport['actualises'] += 1
        else:
            rapport['adoptes'] += 1

    if ecrire:
        db.session.commit()
        logger.info('Import du catalogue : %s', {k: (len(v) if isinstance(v, list) else v)
                                                 for k, v in rapport.items()})
    return rapport, None
