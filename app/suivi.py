"""Éléments suivis, lus par un outil tiers : échéances, alertes, synthèse, recherche.

Ce que l'assistant chatIA de la Ville vient lire par l'API (routes /api/chatia/…,
app/api.py), avec sa propre clé. LECTURE SEULE : rien ici n'écrit en base.

Ce qui sort, et ce qui ne sort jamais :
- un élément se présente par son nom (celui des listes, des alertes et de
  l'agenda), son échéance, son statut, son responsable quand la fiche en a un,
  et le lien vers sa fiche ;
- AUCUN secret : ni code de révocation d'un certificat, ni mot de passe, ni clé,
  ni destinataire d'alerte. Les textes libres (description, notes, résultat,
  périmètre, commentaire) restent aussi dedans : on y colle parfois ce qui ne
  devrait pas y être, et rien ne permet de le savoir de l'extérieur. La
  recherche ne les lit pas non plus — une correspondance trahirait leur contenu
  mot par mot.

Deux familles d'échéances :
- DATÉES (mots de passe, certificats, domaines, tests, revues, contrats,
  matériel) : retenues quand la date tombe dans l'horizon demandé, ou est déjà
  passée ;
- D'ÉTAT (sauvegardes non vérifiées, mises à jour en attente, logiciels en fin
  de vie) : retenues quand le statut est critique ou urgent, quel que soit
  l'horizon — une sauvegarde en échec n'attend pas une date.
Une fiche sans date (« à compléter ») n'est pas une échéance : elle compte dans
la synthèse, pas dans la liste des échéances.

Les ALERTES, elles, sont les fiches critiques ou urgentes du tableau de bord
(hors alertes reportées) : la règle de la synthèse, dont elles détaillent les
comptes, une ligne par fiche — sans date comprises, quel que soit l'horizon.
"""
import unicodedata
from datetime import datetime, timezone, timedelta

from flask import current_app

from app import features
from app.libelles import delai, status_label
from app.models import (Account, Certificate, Domain, Backup, TestTask,
                        AccessReview, SystemUpdate, Equipment, Software, Contract,
                        AlertLog, AlertSnooze, SchedulerRun, CRITICALITY_LABELS)

# Type exposé -> (libellé, catégorie de droits de Sentinelle, entity_type des
# alertes et des reports). La catégorie dit si le module est actif : un module
# coupé dans les Préférences ne se lit pas plus par l'API qu'à l'écran.
TYPES = {
    'mot_de_passe': ('Mots de passe', 'accounts', 'account'),
    'certificat': ('Certificats', 'certificates', 'certificate'),
    'domaine': ('Noms de domaine', 'domains', 'domain'),
    'sauvegarde': ('Sauvegardes', 'backups', 'backup'),
    'test': ('Tests récurrents', 'tests', 'test'),
    'revue': ('Revues de droits', 'reviews', 'review'),
    'mise_a_jour': ('Mises à jour', 'updates', 'update'),
    'contrat': ('Contrats', 'contracts', 'contract'),
    'materiel': ('Matériel', 'inventory', 'equipment'),
    'logiciel': ('Logiciels', 'software', 'software'),
}
_PAR_ENTITE = {entite: t for t, (_l, _c, entite) in TYPES.items()}

STATUTS = ('danger', 'warning', 'info', 'success')
HORIZON_DEFAUT = 30
HORIZON_MAX = 730
ELEMENTS_MAX = 300
RECHERCHE_MIN = 2
RECHERCHE_MAX = 100
RESULTATS_MAX = 20

_ETATS_TACHE = {'pending': 'À faire', 'success': 'Réussi', 'completed': 'Réussi',
                'failed': 'En échec'}
_ETATS_MAJ = {'up_to_date': 'À jour', 'update_available': 'Mise à jour disponible',
              'critical': 'Mise à jour critique'}


# ─────────────────────────────────────────────────────────── paramètres reçus

def lire_horizon(brut):
    """« dans » : nombre de jours, HORIZON_DEFAUT si absent. ValueError sinon."""
    if brut is None or str(brut).strip() == '':
        return HORIZON_DEFAUT
    try:
        jours = int(str(brut).strip())
    except ValueError:
        jours = -1
    if not 0 <= jours <= HORIZON_MAX:
        raise ValueError(f'Paramètre « dans » : nombre de jours attendu, de 0 à {HORIZON_MAX}.')
    return jours


def lire_types(valeurs):
    """« type » : un ou plusieurs types (répétés ou séparés par des virgules).
    Liste vide = tous. ValueError pour un type inconnu, avec la liste admise."""
    demandes = []
    for v in valeurs or []:
        demandes += [x.strip().lower() for x in str(v).split(',') if x.strip()]
    inconnus = [t for t in demandes if t not in TYPES]
    if inconnus:
        raise ValueError(f"Type inconnu : {', '.join(inconnus)}. Types admis : "
                         f"{', '.join(TYPES)}.")
    return list(dict.fromkeys(demandes))


def lire_oui(brut):
    """« 1 », « true », « oui » : vrai ; absent ou autre chose : faux."""
    return str(brut or '').strip().lower() in ('1', 'true', 'oui', 'yes')


def lire_recherche(brut):
    """« q » : le texte cherché, espaces réduits. ValueError s'il est trop court
    ou trop long."""
    q = ' '.join(str(brut or '').split())
    if not RECHERCHE_MIN <= len(q) <= RECHERCHE_MAX:
        raise ValueError(f'Paramètre « q » : de {RECHERCHE_MIN} à {RECHERCHE_MAX} caractères.')
    return q


# ─────────────────────────────────────────────────────────── outils communs

def _aujourdhui():
    return datetime.now(timezone.utc).date()


def _maintenant():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _actifs(types=None):
    """Types demandés (tous par défaut) dont le module est actif."""
    return [t for t in (types or TYPES) if features.category_enabled(TYPES[t][1])]


def _base():
    return (current_app.config.get('APP_BASE_URL') or '').rstrip('/')


def _jour(d):
    return d.isoformat() if d else None


def _horodatage(dt):
    """Instant stocké en UTC sans fuseau (SQLite) -> ISO 8601 avec fuseau."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec='minutes')


def _reports(aujourdhui):
    """{(entity_type, id): fin du report} des reports d'alerte en cours."""
    return {(s.entity_type, s.entity_id): s.snoozed_until
            for s in AlertSnooze.query.filter(AlertSnooze.snoozed_until >= aujourdhui).all()}


def _simplifier(texte):
    """Minuscules sans accents : « Échéance » se trouve en tapant « echeance »."""
    texte = unicodedata.normalize('NFD', str(texte or '').lower())
    return ''.join(c for c in texte if unicodedata.category(c) != 'Mn')


def _nom_de(lie):
    return lie.name if lie is not None else None


class _Contexte:
    """Ce que partagent les éléments d'une même réponse : le jour, les reports
    en cours et l'adresse de Sentinelle (lus une fois)."""

    def __init__(self):
        self.aujourdhui = _aujourdhui()
        self.reports = _reports(self.aujourdhui)
        self.base = _base()

    def element(self, type_, o, nom, chemin, statut, *, objet, echeance=None, detail='',
                type_libelle=None, responsable=None, **autres):
        """Un élément suivi, dans la forme commune à toutes les routes."""
        jours = (echeance - self.aujourdhui).days if echeance else None
        element = {
            'type': type_,
            'type_libelle': type_libelle or TYPES[type_][0],
            'id': o.id,
            'nom': nom,
            'objet': objet,
            'echeance': _jour(echeance),
            'jours_restants': jours,
            'en_retard': jours is not None and jours < 0,
            'detail': detail,
            'statut': statut,
            'statut_libelle': status_label(statut),
            'responsable': responsable or None,
            'reporte_jusqu_au': _jour(self.reports.get((TYPES[type_][2], o.id))),
            'lien': self.base + chemin,
        }
        element.update(autres)
        return element


# ─────────────────────────────────────────────────────────── une fiche -> ses éléments
# Chaque fonction rend la liste des échéances d'une fiche : une seule, sauf le
# matériel (garantie, fin de support de l'OS).

def _compte(a, ctx):
    d = a.next_password_change
    return [ctx.element(
        'mot_de_passe', a, f'{a.service_name} ({a.username})', f'/accounts/{a.id}', a.status(),
        objet='Rotation du mot de passe', echeance=d, type_libelle='Mot de passe',
        detail=('Mot de passe à renouveler ' + delai(d, today=ctx.aujourdhui)
                if d else 'Date de rotation non renseignée'))]


def _certificat(c, ctx):
    autres = {}
    if c.kind == 'signature' and c.holder_label():
        autres['titulaire'] = c.holder_label()
    if c.validity == 'revoque':
        detail = 'Certificat révoqué : hors surveillance'
    elif c.expiry_date:
        detail = 'Certificat ' + delai(c.expiry_date, passe='expiré depuis', futur='expire dans',
                                       today=ctx.aujourdhui)
    else:
        detail = "Date d'expiration à compléter"
    return [ctx.element(
        'certificat', c, c.label(), f'/certificates/{c.id}', c.status(),
        objet='Expiration du certificat', echeance=c.expiry_date, type_libelle=c.kind_label(),
        detail=detail, **autres)]


def _domaine(d, ctx):
    return [ctx.element(
        'domaine', d, d.name, f'/domains/{d.id}', d.status(),
        objet='Expiration du nom de domaine', echeance=d.expiry_date, type_libelle='Domaine',
        detail=('Domaine ' + delai(d.expiry_date, passe='expiré depuis', futur='expire dans',
                                   today=ctx.aujourdhui)
                if d.expiry_date else "Date d'expiration à compléter"))]


def _sauvegarde(b, ctx):
    dernier = b.last_ok_check()
    # Le contrôle réussi suivant était attendu une période après le dernier.
    attendu = dernier.check_date + timedelta(days=b.expected_interval_days()) if dernier else None
    du_jour = b.today_check()
    if du_jour and du_jour.status == 'failed':
        detail = 'Contrôle du jour en échec'
    elif du_jour and du_jour.status == 'warning':
        detail = 'Contrôle du jour en avertissement'
    elif dernier is None:
        detail = 'Aucun contrôle réussi enregistré'
    else:
        detail = (f'Dernier contrôle réussi il y a {b.days_since_last_ok()} j '
                  f'({b.frequency_label().lower()})')
    return [ctx.element(
        'sauvegarde', b, b.service_name, f'/backups/{b.id}', b.computed_status(),
        objet='Vérification de la sauvegarde', echeance=attendu, type_libelle='Sauvegarde',
        detail=detail)]


def _test(t, ctx):
    detail = ('Test ' + delai(t.next_due, futur='à faire dans', today=ctx.aujourdhui)
              if t.next_due else 'Échéance non planifiée')
    if t.status == 'failed':
        detail += ' — dernier passage en échec'
    return [ctx.element(
        'test', t, t.name, f'/tests/{t.id}', t.computed_status(),
        objet=f'Test à effectuer ({t.test_type})' if t.test_type else 'Test à effectuer',
        echeance=t.next_due, type_libelle='Test récurrent', detail=detail)]


def _revue(r, ctx):
    return [ctx.element(
        'revue', r, r.application, f'/reviews/{r.id}', r.computed_status(),
        objet="Revue des droits d'accès", echeance=r.next_review, type_libelle='Revue de droits',
        responsable=r.responsible,
        detail=('Revue ' + delai(r.next_review, today=ctx.aujourdhui)
                if r.next_review else 'Revue à planifier'))]


def _mise_a_jour(u, ctx):
    versions = ' → '.join(v for v in (u.current_version, u.latest_version) if v)
    detail = _ETATS_MAJ.get(u.status, u.status or '') + (f' ({versions})' if versions else '')
    return [ctx.element(
        'mise_a_jour', u, u.name, f'/updates/{u.id}', u.status_color(),
        objet='Mise à jour', type_libelle='Mise à jour', detail=detail)]


def _contrat(c, ctx):
    limite = c.action_deadline()
    if limite is None:
        detail = 'Échéance à renseigner'
    else:
        detail = delai(limite, passe='préavis dépassé de', futur='agir dans',
                       today=ctx.aujourdhui).capitalize()
        detail += f" (fin du contrat le {c.end_date.strftime('%d/%m/%Y')}"
        detail += f', préavis {c.notice_days} j)' if c.notice_days else ')'
    return [ctx.element(
        'contrat', c, c.name, f'/contracts/{c.id}', c.status(),
        objet='Échéance / préavis du contrat', echeance=limite, type_libelle='Contrat',
        detail=detail, fournisseur=_nom_de(c.supplier))]


def _materiel(e, ctx):
    """Fin de garantie et fin de support de l'OS (cache local d'endoflife.date :
    aucun appel réseau)."""
    elements = []
    chemin = f'/inventory/{e.id}'
    if e.warranty_end:
        elements.append(ctx.element(
            'materiel', e, f'{e.name} (garantie)', chemin, e.warranty_status(),
            objet='Fin de garantie matérielle', echeance=e.warranty_end,
            type_libelle=e.kind_label(),
            detail='Garantie ' + delai(e.warranty_end, passe='expirée depuis',
                                       futur='expire dans', today=ctx.aujourdhui)))
    info = e.eol_info()
    if info and info.get('eol_date'):
        systeme = ' '.join(x for x in (e.os, e.os_version) if x)
        elements.append(ctx.element(
            'materiel', e, f'{e.name} (fin de support OS)', chemin, info.get('status') or 'info',
            objet="Fin de support du système d'exploitation", echeance=info['eol_date'],
            type_libelle=e.kind_label(),
            detail=f'{systeme} : fin de support '
            + delai(info['eol_date'], passe='dépassée de', futur='dans', today=ctx.aujourdhui)))
    return elements


def _logiciel(s, ctx):
    statut = s.computed_status()
    if statut == 'danger':
        detail = 'Mise à jour critique en attente'
    elif s.lifecycle == 'fin_de_vie':
        detail = 'En fin de vie, successeur à trouver'
    elif statut == 'warning':
        detail = 'Mise à jour disponible'
    else:
        detail = s.lifecycle_label()
    return [ctx.element(
        'logiciel', s, s.name, f'/inventory/logiciels/{s.id}', statut,
        objet='Cycle de vie du logiciel', type_libelle='Logiciel', responsable=s.responsible,
        detail=detail)]


# Type -> (modèle, éléments d'une fiche, statut de la fiche). Le statut est celui
# des vignettes du tableau de bord : UN par fiche, quand le matériel a deux
# échéances.
_SOURCES = {
    'mot_de_passe': (Account, _compte, lambda o: o.status()),
    'certificat': (Certificate, _certificat, lambda o: o.status()),
    'domaine': (Domain, _domaine, lambda o: o.status()),
    'sauvegarde': (Backup, _sauvegarde, lambda o: o.computed_status()),
    'test': (TestTask, _test, lambda o: o.computed_status()),
    'revue': (AccessReview, _revue, lambda o: o.computed_status()),
    'mise_a_jour': (SystemUpdate, _mise_a_jour, lambda o: o.status_color()),
    'contrat': (Contract, _contrat, lambda o: o.status()),
    'materiel': (Equipment, _materiel, lambda o: o.computed_status()),
    'logiciel': (Software, _logiciel, lambda o: o.computed_status()),
}
# Échéances d'ÉTAT : retenues sur leur statut, pas sur une date (voir l'en-tête).
_PAR_ETAT = {'sauvegarde', 'mise_a_jour', 'logiciel'}


def _fiches(type_):
    return _SOURCES[type_][0].query.filter_by(is_active=True).all()


def _retenue(type_, o, el, limite):
    """L'élément est-il une échéance de l'horizon ?"""
    if type_ == 'logiciel':
        # Une MAJ critique d'un logiciel paraît déjà en « mise_a_jour » : le
        # logiciel ne s'y ajoute que pour sa fin de vie.
        return o.lifecycle == 'fin_de_vie'
    if type_ in _PAR_ETAT:
        return el['statut'] in ('danger', 'warning')
    if type_ == 'certificat' and not o.monitored():
        return False  # révoqué ou sans date : hors surveillance, comme dans l'agenda
    return el['echeance'] is not None and el['echeance'] <= limite.isoformat()


# ─────────────────────────────────────────────────────────── routes

def echeances(dans=HORIZON_DEFAUT, types=None):
    """Ce qui arrive à échéance dans `dans` jours, ou est déjà en retard."""
    ctx = _Contexte()
    limite = ctx.aujourdhui + timedelta(days=dans)
    retenus = []
    for t in _actifs(types):
        construire = _SOURCES[t][1]
        for o in _fiches(t):
            retenus += [el for el in construire(o, ctx) if _retenue(t, o, el, limite)]
    rang = {s: i for i, s in enumerate(STATUTS)}
    # Les échéances d'état (sans date) d'abord, puis par date ; à date égale,
    # la plus grave avant.
    retenus.sort(key=lambda e: (e['echeance'] or '', rang.get(e['statut'], 9), e['nom'].lower()))
    return {
        'genere_le': _maintenant(),
        'aujourd_hui': ctx.aujourdhui.isoformat(),
        'dans': dans,
        'jusqu_au': limite.isoformat(),
        'types': _actifs(types),
        'total': len(retenus),
        'en_retard': sum(1 for e in retenus if e['en_retard']),
        'tronque': len(retenus) > ELEMENTS_MAX,
        'elements': retenus[:ELEMENTS_MAX],
    }


def alertes(types=None, reportees=False):
    """Les alertes ouvertes, une par fiche : fiches critiques ou urgentes, hors
    alertes reportées (sauf `reportees`). Même règle que la synthèse, dont les
    comptes concordent ; le matériel se présente par son statut d'ensemble et ses
    motifs. Les critiques d'abord, puis l'échéance la plus proche (retards en
    tête), les fiches sans date à la fin."""
    ctx = _Contexte()
    retenus = []
    for t in _actifs(types):
        statut_de = _SOURCES[t][2]
        for o in _fiches(t):
            s = statut_de(o)
            if s not in ('danger', 'warning'):
                continue
            if (TYPES[t][2], o.id) in ctx.reports and not reportees:
                continue
            el = _fiche(t, o, ctx)
            el.update(statut=s, statut_libelle=status_label(s))  # le statut de la fiche, celui des comptes
            retenus.append(el)
    rang = {s: i for i, s in enumerate(STATUTS)}
    retenus.sort(key=lambda e: (rang.get(e['statut'], 9), e['echeance'] is None, e['echeance'] or '',
                                e['nom'].lower()))
    return {
        'genere_le': _maintenant(),
        'aujourd_hui': ctx.aujourdhui.isoformat(),
        'types': _actifs(types),
        'reportees_incluses': bool(reportees),
        'total': len(retenus),
        'critiques': sum(1 for e in retenus if e['statut'] == 'danger'),
        'urgentes': sum(1 for e in retenus if e['statut'] == 'warning'),
        'tronque': len(retenus) > ELEMENTS_MAX,
        'elements': retenus[:ELEMENTS_MAX],
    }


def synthese():
    """Comptes par type et par statut, conformité globale et alertes : ce que
    disent le tableau de bord et le récapitulatif du matin."""
    from app.app_settings import get_conformity_categories
    aujourdhui = _aujourdhui()
    reports = _reports(aujourdhui)
    categories = []
    a_traiter = {}
    for t in _actifs():
        _modele, _construire, statut_de = _SOURCES[t]
        compte = dict.fromkeys(STATUTS, 0)
        critiques = urgents = 0
        for o in _fiches(t):
            s = statut_de(o)
            compte[s if s in compte else 'info'] += 1
            # Une alerte reportée n'est plus « ouverte » : quelqu'un l'a vue.
            if (TYPES[t][2], o.id) not in reports:
                critiques += s == 'danger'
                urgents += s == 'warning'
        categories.append({'type': t, 'libelle': TYPES[t][0], 'total': sum(compte.values()),
                           'par_statut': compte})
        if critiques or urgents:
            a_traiter[t] = {'critiques': critiques, 'urgents': urgents}

    # Conformité globale : la règle du tableau de bord (catégories retenues dans
    # les Préférences, part des fiches au vert).
    retenues = set(get_conformity_categories())
    comptees = [c for c in categories if TYPES[c['type']][1] in retenues]
    total = sum(c['total'] for c in comptees)
    ok = sum(c['par_statut']['success'] for c in comptees)

    depuis = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    recentes = AlertLog.query.filter(AlertLog.sent_at >= depuis)
    dernieres = AlertLog.query.order_by(AlertLog.sent_at.desc()).limit(5).all()
    tache = SchedulerRun.query.order_by(SchedulerRun.run_at.desc()).first()
    totaux = {s: sum(c['par_statut'][s] for c in categories) for s in STATUTS}
    totaux['total'] = sum(c['total'] for c in categories)
    return {
        'genere_le': _maintenant(),
        'aujourd_hui': aujourdhui.isoformat(),
        'categories': categories,
        'totaux': totaux,
        'conformite': round(100 * ok / total) if total else 100,
        'alertes': {
            'ouvertes': sum(v['critiques'] + v['urgents'] for v in a_traiter.values()),
            'critiques': sum(v['critiques'] for v in a_traiter.values()),
            'urgentes': sum(v['urgents'] for v in a_traiter.values()),
            'par_type': a_traiter,
            'reportees': len(reports),
            'envoyees_7_jours': recentes.filter(AlertLog.status == 'sent').count(),
            'echecs_7_jours': recentes.filter(AlertLog.status == 'failed').count(),
            # Ni le message (il peut porter l'erreur SMTP), ni les destinataires.
            'dernieres': [{'date': _horodatage(a.sent_at),
                           'type': _PAR_ENTITE.get(a.entity_type, a.entity_type),
                           'nom': a.entity_name, 'envoyee': a.status == 'sent'}
                          for a in dernieres],
        },
        'derniere_tache_planifiee': _horodatage(tache.run_at) if tache else None,
        'lien': _base() + '/',
    }


def _cherche_dans(type_, o):
    """Où chercher, par type : les noms, et les personnes ou sociétés nommées sur
    la fiche. Jamais les textes libres (voir l'en-tête)."""
    if type_ == 'mot_de_passe':
        return [o.service_name, o.username, _nom_de(o.software)]
    if type_ == 'certificat':
        return [o.service_name, o.domain, o.holder, o.first_name, o.issuer, _nom_de(o.supplier)]
    if type_ == 'domaine':
        return [o.name, o.registrar]
    if type_ == 'sauvegarde':
        return [o.service_name, o.backup_type, _nom_de(o.equipment)]
    if type_ == 'test':
        return [o.name, o.test_type, _nom_de(o.software)]
    if type_ == 'revue':
        return [o.application, o.responsible]
    if type_ == 'contrat':
        return [o.name, o.reference, _nom_de(o.supplier)]
    if type_ == 'logiciel':
        return [o.name, o.responsible, _nom_de(o.supplier)]
    return [o.name]  # mise_a_jour, materiel


def _details(type_, o):
    """Ce que la fiche dit d'utile, sans secret ni texte libre."""
    if type_ == 'mot_de_passe':
        return {'identifiant': o.username, 'service': o.service_name,
                'derniere_rotation': _jour(o.last_password_change),
                'rotation_jours': o.rotation_days, 'logiciel': _nom_de(o.software)}
    if type_ == 'certificat':
        # Ni code de révocation (secret opératoire), ni montant, ni imputation.
        return {'nature': o.kind_label(), 'domaine': o.domain, 'emetteur': o.issuer,
                'autorite': _nom_de(o.supplier), 'renouvellement_auto': bool(o.auto_renew),
                'validite': o.validity_label(), 'titulaire': o.holder_label() or None,
                'qualite': o.holder_role, 'usage': o.usage_label() or None,
                'support': o.support_label() or None, 'niveau': o.level}
    if type_ == 'domaine':
        return {'bureau_enregistrement': o.registrar, 'renouvellement_auto': bool(o.auto_renew),
                'surveillance_ct': bool(o.ct_enabled),
                'certificats_ct_nouveaux': o.ct_new_count()}
    if type_ == 'sauvegarde':
        dernier = o.last_ok_check()
        return {'type': o.backup_type, 'frequence': o.frequency_label(),
                'dernier_controle_reussi': _jour(dernier.check_date) if dernier else None,
                'taux_reussite_30_jours': o.success_rate(), 'equipement': _nom_de(o.equipment)}
    if type_ == 'test':
        return {'nature': o.test_type, 'dernier_passage': _jour(o.last_performed),
                'frequence_jours': o.frequency_days,
                'etat': _ETATS_TACHE.get(o.status, o.status), 'logiciel': _nom_de(o.software)}
    if type_ == 'revue':
        return {'derniere_revue': _jour(o.last_review), 'frequence_jours': o.frequency_days,
                'etat': _ETATS_TACHE.get(o.status, o.status), 'logiciel': _nom_de(o.software)}
    if type_ == 'mise_a_jour':
        return {'version_actuelle': o.current_version, 'version_disponible': o.latest_version,
                'etat': _ETATS_MAJ.get(o.status, o.status),
                'derniere_mise_a_jour': _jour(o.last_update),
                'logiciel': _nom_de(o.software), 'equipement': _nom_de(o.equipment)}
    if type_ == 'contrat':
        return {'type': o.kind_label() or None, 'nature': o.nature_label() or None,
                'fournisseur': _nom_de(o.supplier), 'reference': o.reference,
                'debut': _jour(o.start_date), 'fin': _jour(o.end_date),
                'preavis_jours': o.notice_days, 'tacite_reconduction': bool(o.auto_renew),
                'date_limite_action': _jour(o.action_deadline())}
    if type_ == 'materiel':
        info = o.eol_info() or {}
        return {'nature': o.kind_label(), 'environnement': o.env_label() or None,
                'criticite': CRITICALITY_LABELS.get(o.criticality),
                'fin_garantie': _jour(o.warranty_end),
                'systeme': ' '.join(x for x in (o.os, o.os_version) if x) or None,
                'fin_support_systeme': _jour(info.get('eol_date')),
                'points_attention': o.status_reasons()}
    if type_ == 'logiciel':
        return {'version': o.version, 'cycle_de_vie': o.lifecycle_label(),
                'hebergement': o.hosting_label(), 'editeur': _nom_de(o.supplier),
                'criticite': o.criticality_label() or None,
                'responsable_technique': o.tech_responsible}
    return {}


def _fiche(type_, o, ctx):
    """L'élément qui présente une fiche trouvée. Le matériel se présente par son
    statut d'ensemble (garantie, sauvegarde, OS), pas par une seule échéance."""
    if type_ == 'materiel':
        statut = o.computed_status()
        return ctx.element(
            'materiel', o, o.name, f'/inventory/{o.id}', statut,
            objet='Fin de garantie matérielle', echeance=o.warranty_end,
            type_libelle=o.kind_label(),
            detail='; '.join(o.status_reasons()) or status_label(statut))
    return _SOURCES[type_][1](o, ctx)[0]


def recherche(q, types=None):
    """Fiches dont le nom (ou une personne, une société nommée) contient `q`,
    sans tenir compte des accents ni des majuscules."""
    ctx = _Contexte()
    cle = _simplifier(q)
    trouvees = [(t, o) for t in _actifs(types) for o in _fiches(t)
                if any(cle in _simplifier(v) for v in _cherche_dans(t, o) if v)]
    elements = []
    for t, o in trouvees[:RESULTATS_MAX]:
        el = _fiche(t, o, ctx)
        el['details'] = _details(t, o)
        elements.append(el)
    return {
        'genere_le': _maintenant(),
        'q': q,
        'total': len(trouvees),
        'tronque': len(trouvees) > RESULTATS_MAX,
        'elements': elements,
    }
