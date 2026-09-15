"""Reprise des données de SoftInventory dans Sentinelle.

SoftInventory tenait l'inventaire des logiciels de la collectivité : les
éditeurs et leurs contacts, les marchés et leurs pièces, les devis, les
certificats électroniques, les services utilisateurs, les pièces jointes. Ses
fonctionnalités vivent désormais ici ; ce script y verse ses données, une fois,
pour qu'il n'y ait plus qu'un seul outil.

── Usage ──

    .\\venv\\Scripts\\python.exe tools\\reprise_softinventory.py --essai
    .\\venv\\Scripts\\python.exe tools\\reprise_softinventory.py

`--essai` lit tout, compte tout, et n'écrit rien : de quoi lire le rapport et
voir ce qui ne se rapproche pas avant d'engager la base.

La source par défaut est la base restaurée depuis le dump :

    docker exec softinventory-db psql -U softinventory -d postgres \\
        -c "CREATE DATABASE reprise OWNER softinventory;"
    docker exec -i softinventory-db pg_restore -U softinventory -d reprise \\
        --no-owner --no-acl < sauvegardes/softinventory-AAAAMMJJ-HHMM.dump

`--dsn` permet d'en viser une autre (la base vivante, par exemple).

── Rejouable ──

Chaque objet repris laisse une ligne dans `import_map` : relancer le script
retrouve les fiches déjà créées au lieu de les doubler. La première passe
révèle toujours quelque chose à corriger, et sans cela il faudrait vider la
base entre deux essais. La table s'efface d'un DELETE le jour où la reprise
est derrière nous.

── Ce qui ne se rapproche pas ──

Le parc appartient à Sentinelle : les serveurs de SoftInventory se rapprochent
des équipements d'ici PAR LE NOM, puis à la ponctuation près. Ceux qui n'y
trouvent toujours pas leur jumeau sont CRÉÉS, avec ce que SoftInventory en
sait — nom, famille d'OS, version, localisation, virtuel ou non, notes. Ce
n'est pas une fiche inventée : c'est une fiche reprise, à compléter (ni IP, ni
VLAN, ni garantie, que SoftInventory ne tenait pas). Les abandonner reviendrait
à perdre les installations logiciel↔serveur qui s'y rattachent.

`--sans-creer-serveurs` s'en tient au rapprochement et nomme les manquants,
pour une reprise qui ne doit rien ajouter au parc.
"""
import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DSN_DEFAUT = 'postgresql://softinventory:dev@localhost:5433/reprise'

# La criticité se rapproche par LIBELLÉ, pas par rang : SoftInventory ordonne du
# plus grave au moins grave, Sentinelle chiffre l'inverse (1 faible … 4
# critique). Se fier au rang aurait retourné toute l'échelle sans rien signaler.
CRITICITE = {'critique': 4, 'élevée': 3, 'elevee': 3, 'modérée': 2, 'moderee': 2,
             'faible': 1}

# Ce qu'est la société, dans les mots de l'annuaire d'ici.
CATEGORIE_EDITEUR = {'editeur': 'editor', 'autorite_certification': 'ca'}

# La nature de l'acte décide du type affiché : un marché public se lit comme
# tel, le reste retombe sur « maintenance », le cas ordinaire.
KIND_CONTRAT = {'marche': 'market', 'contrat': 'maintenance'}


def _dec(v):
    """Un Decimal PostgreSQL devient un float SQLite. None reste None : zéro et
    « non renseigné » ne disent pas la même chose d'un montant."""
    return float(v) if isinstance(v, Decimal) else v


def _txt(v, n=None):
    """Une chaîne vide devient NULL : SoftInventory écrit '' là où Sentinelle
    laisse vide, et recopier des chaînes vides ferait afficher « » au lieu
    du tiret qui dit « non renseigné »."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    return v[:n] if n else v


class Reprise:
    def __init__(self, cur, db, ecrire=True, creer_serveurs=True):
        self.cur = cur
        self.db = db
        self.ecrire = ecrire
        self.creer_serveurs = creer_serveurs
        self.rapport = {}
        self.avertissements = []
        # Les correspondances posées PENDANT ce passage. Elles ne partent en
        # base que si l'on écrit ; en essai elles restent ici, faute de quoi
        # chaque étape trouverait ses parents introuvables et le rapport
        # annoncerait 439 pièces jointes orphelines qui ne le sont pas.
        self.memo = {}

    # ── Correspondance d'un import à l'autre ──

    def _lire_map(self, kind):
        from app.models import ImportMap
        table = {m.remote_id: m.local_id
                 for m in ImportMap.query.filter_by(kind=kind).all()}
        table.update(self.memo.get(kind, {}))
        return table

    def _noter(self, kind, remote_id, local_id):
        from app.models import ImportMap
        # En essai, un identifiant NÉGATIF : il ne désigne aucune fiche, mais il
        # est vrai et unique, de sorte que les étapes suivantes rapprochent
        # leurs parents et comptent juste.
        self.memo.setdefault(kind, {})[remote_id] = local_id if self.ecrire else -remote_id
        if not self.ecrire:
            return
        self.db.session.merge(ImportMap(kind=kind, remote_id=remote_id,
                                        local_id=local_id))

    def _compte(self, quoi, n=1):
        self.rapport[quoi] = self.rapport.get(quoi, 0) + n

    def _rows(self, table, order='id'):
        self.cur.execute(f'SELECT * FROM {table} ORDER BY {order}')
        return self.cur.fetchall()

    # ── Les référentiels, d'abord : tout le reste s'y rattache ──

    def services(self):
        from app.models import UserService
        deja = self._lire_map('service')
        for r in self._rows('services_utilisateurs'):
            if r['id'] in deja:
                continue
            # Le nom fait foi : un service saisi ici avant la reprise ne se
            # dédouble pas, il se retrouve.
            sv = UserService.query.filter_by(name=r['nom']).first()
            if sv is None:
                sv = UserService(name=r['nom'][:128],
                                 contact_name=_txt(r['contact_nom'], 128),
                                 contact_email=_txt(r['contact_email'], 120),
                                 contact_phone=_txt(r['contact_telephone'], 64),
                                 position=r['position'] or 0)
                if self.ecrire:
                    self.db.session.add(sv)
                    self.db.session.flush()
                self._compte('services créés')
            else:
                self._compte('services retrouvés')
            self._noter('service', r['id'], sv.id if self.ecrire else 0)

    def referentiels(self):
        from app.models import Referential
        for table, kind in (('technologies', 'technology'),
                            ('categories_documents', 'doc_category')):
            deja = self._lire_map(kind)
            for r in self._rows(table):
                if r['id'] in deja:
                    continue
                item = Referential.query.filter_by(kind=kind, label=r['label']).first()
                if item is None:
                    item = Referential(kind=kind, label=r['label'][:64],
                                       position=r['position'] or 0)
                    if self.ecrire:
                        self.db.session.add(item)
                        self.db.session.flush()
                    self._compte(f'{kind} créés')
                self._noter(kind, r['id'], item.id if self.ecrire else 0)

    def editeurs(self):
        from app.models import Supplier
        deja = self._lire_map('supplier')
        for r in self._rows('editeurs'):
            if r['id'] in deja:
                continue
            s = Supplier.query.filter(
                self.db.func.lower(Supplier.name) == r['nom'].strip().lower()).first()
            if s is None:
                s = Supplier(name=r['nom'][:128])
                if self.ecrire:
                    self.db.session.add(s)
                self._compte('éditeurs créés')
            else:
                self._compte('éditeurs retrouvés')
            s.kind = CATEGORIE_EDITEUR.get(r.get('categorie'), 'editor')
            for champ, colonne, n in (
                    ('address', 'adresse', 256), ('postal_code', 'code_postal', 16),
                    ('city', 'ville', 128), ('phone', 'telephone', 64),
                    ('email', 'email', 128), ('website', 'site_web', 256),
                    ('support_url', 'support_url', 256),
                    ('support_email', 'support_email', 128),
                    ('support_phone', 'support_telephone', 64),
                    ('customer_ref', 'numero_client', 128),
                    ('hours', 'support_horaires', 128),
                    ('hours2', 'support_horaires_2', 128),
                    ('commercial_contact', 'commercial_contact', 128),
                    ('commercial_phone', 'commercial_telephone', 64),
                    ('commercial_email', 'commercial_email', 128),
                    ('commercial_contact2', 'commercial_contact_2', 128),
                    ('commercial_phone2', 'commercial_telephone_2', 64),
                    ('commercial_email2', 'commercial_email_2', 128),
                    ('admin_contact', 'admin_contact', 128),
                    ('admin_phone', 'admin_telephone', 64),
                    ('admin_email', 'admin_email', 128),
                    ('dpo_contact', 'dpo_contact', 128),
                    ('dpo_phone', 'dpo_telephone', 64),
                    ('dpo_email', 'dpo_email', 128),
                    ('notes', 'notes', None)):
                setattr(s, champ, _txt(r.get(colonne), n))
            if self.ecrire:
                self.db.session.flush()
            self._noter('supplier', r['id'], s.id if self.ecrire else 0)

    # ── Le catalogue ──

    def logiciels(self):
        from app.models import Software, HOSTING_LABELS, LIFECYCLE_LABELS
        crit = {r['id']: CRITICITE.get((r['label'] or '').strip().lower())
                for r in self._rows('criticites')}
        editeurs = self._lire_map('supplier')
        technos = self._lire_map('technology')
        deja = self._lire_map('software')

        for r in self._rows('logiciels'):
            if r['id'] in deja:
                continue
            sw = Software.query.filter(
                self.db.func.lower(Software.name) == r['nom'].strip().lower()).first()
            if sw is None:
                sw = Software(name=r['nom'][:128])
                if self.ecrire:
                    self.db.session.add(sw)
                self._compte('logiciels créés')
            else:
                self._compte('logiciels retrouvés')

            heb = r.get('hebergement')
            sw.hosting = heb if heb in HOSTING_LABELS else 'on_premise'
            statut = r.get('statut')
            sw.lifecycle = statut if statut in LIFECYCLE_LABELS else 'production'
            sw.description = _txt(r.get('description'))
            sw.supplier_id = editeurs.get(r.get('editeur_id'))
            sw.technology_id = technos.get(r.get('technologie_id'))
            sw.criticality = crit.get(r.get('criticite_id'))
            sw.source_type = r.get('type_source') or 'proprietaire'
            sw.version = _txt(r.get('version_installee'), 64)
            sw.url = _txt(r.get('url'), 256)
            sw.service_date = r.get('date_mise_en_service')
            sw.auth_mode = _txt(r.get('authentification'), 16)
            sw.auth_strong = bool(r.get('authentification_forte'))
            sw.users_count = r.get('nb_utilisateurs')
            sw.users_max = r.get('nb_max_utilisateurs')
            sw.responsible = _txt(r.get('referent_metier'), 128)
            sw.responsible_email = _txt(r.get('referent_metier_email'), 120)
            sw.tech_responsible = _txt(r.get('referent_technique'), 128)
            sw.tech_responsible_email = _txt(r.get('referent_technique_email'), 120)
            sw.internal_dev = bool(r.get('developpement_interne'))
            sw.no_server = bool(r.get('sans_serveur'))
            # `conteneurise` est apparu APRÈS certains dumps : absent, il vaut
            # faux — c'est l'exception, pas la règle.
            sw.is_docker = bool(r.get('conteneurise'))
            sw.no_contract_note = _txt(r.get('mention_sans_contrat'), 256)
            sw.gdpr_personal_data = bool(r.get('donnees_personnelles'))
            sw.gdpr_categories = _txt(r.get('categories_donnees'), 256)
            sw.gdpr_registry_ref = _txt(r.get('registre_ref'), 64)
            sw.gdpr_location = r.get('localisation_donnees') or 'inconnue'
            if self.ecrire:
                self.db.session.flush()
            self._noter('software', r['id'], sw.id if self.ecrire else 0)

    def logiciels_services(self):
        from app.models import Software, UserService
        logiciels = self._lire_map('software')
        services = self._lire_map('service')
        for r in self._rows('logiciels_services', 'logiciel_id, service_id'):
            sw_id = logiciels.get(r['logiciel_id'])
            sv_id = services.get(r['service_id'])
            if not (sw_id and sv_id):
                continue
            if not self.ecrire:
                self._compte('rattachements à un service')
                continue
            sw = Software.query.get(sw_id)
            sv = UserService.query.get(sv_id)
            if sw is not None and sv is not None and sv not in sw.user_services:
                sw.user_services.append(sv)
                self._compte('rattachements à un service')

    # La famille d'OS de SoftInventory, dans les mots de l'inventaire d'ici.
    _TYPE_OS = {'windows': 'Windows', 'linux': 'Linux'}

    def _creer_equipement(self, serveur):
        """Fait entrer dans le parc un serveur que SoftInventory connaissait et
        que Sentinelle ignore. La fiche est PARTIELLE et le reste : ni IP, ni
        VLAN, ni garantie — SoftInventory ne les tenait pas, et les inventer
        serait pire que de laisser vide. L'observation le dit, pour que celui
        qui ouvrira la fiche sache pourquoi elle est maigre."""
        from app.models import Equipment
        e = Equipment(
            name=(serveur['nom'] or '')[:128],
            # `virtuel` ne distingue pas un NAS d'un serveur physique ; on s'en
            # tient a ce qu'il dit.
            kind='vm' if serveur.get('virtuel') else 'physical',
            os=_txt(self._TYPE_OS.get(serveur.get('type_os')), 128),
            os_version=_txt(serveur.get('os'), 64),
            host_server=_txt(serveur.get('localisation'), 128),
            observations=_txt(serveur.get('notes')))
        # La version d'OS de SoftInventory est en clair (« Ubuntu 22.04.5 LTS ») :
        # elle tient lieu d'OS quand la famille n'est pas renseignee.
        if not e.os and e.os_version:
            e.os, e.os_version = e.os_version[:128], None
        note = 'Fiche reprise de SoftInventory, à compléter (IP, VLAN, garantie).'
        e.observations = f'{e.observations}\n{note}' if e.observations else note
        if self.ecrire:
            self.db.session.add(e)
            self.db.session.flush()
        self._compte('équipements créés')
        return e

    def logiciels_serveurs(self):
        """Les installations. Le parc appartient à Sentinelle : on rapproche PAR
        LE NOM, puis à la ponctuation près, et ce qui ne se rapproche toujours
        pas est repris tel quel plutôt qu'abandonné — sans quoi l'installation
        qui s'y rattache serait perdue."""
        from app.models import Software, Equipment
        logiciels = self._lire_map('software')
        serveurs = {r['id']: r for r in self._rows('serveurs')}
        actifs = Equipment.query.filter_by(is_active=True).all()
        parc = {(e.name or '').strip().lower(): e for e in actifs}
        # Second rapprochement, tolérant à la PONCTUATION seule :
        # « SRV-IPARAPHEUR » et « SRV-I-PARAPHEUR » sont la même machine, et un
        # tiret n'est pas une différence. Il ne joue que si la forme réduite
        # désigne UN SEUL équipement — un rapprochement ambigu est pire
        # qu'aucun, il pose l'application sur la mauvaise machine en silence.
        reduit = {}
        for e in actifs:
            cle = ''.join(c for c in (e.name or '').lower() if c.isalnum())
            reduit.setdefault(cle, []).append(e)
        introuvables = set()
        crees = {}
        for r in self._rows('logiciels_serveurs', 'logiciel_id, serveur_id'):
            serveur = serveurs.get(r['serveur_id']) or {}
            nom = serveur.get('nom') or ''
            e = parc.get(nom.strip().lower())
            if e is None:
                candidats = reduit.get(''.join(c for c in nom.lower() if c.isalnum()), [])
                e = candidats[0] if len(candidats) == 1 else None
            if e is None and self.creer_serveurs and nom:
                # Un seul equipement par serveur, meme s'il porte trois
                # applications : `crees` evite de le recreer a chaque ligne.
                e = crees.get(nom)
                if e is None:
                    e = self._creer_equipement(serveur)
                    crees[nom] = e
                    parc[nom.strip().lower()] = e
            if e is None:
                introuvables.add(nom)
                continue
            sw_id = logiciels.get(r['logiciel_id'])
            if not sw_id:
                continue
            if not self.ecrire:
                self._compte('installations posées')
                continue
            sw = Software.query.get(sw_id)
            if sw is not None and e not in sw.equipments:
                sw.equipments.append(e)
                self._compte('installations posées')
        if crees:
            self.avertissements.append(
                'Serveurs repris de SoftInventory et AJOUTÉS au parc, à compléter '
                '(IP, VLAN, garantie) : ' + ', '.join(sorted(crees)))
        if introuvables:
            self.avertissements.append(
                'Serveurs sans équipement correspondant dans le parc, '
                'installations non posées : ' + ', '.join(sorted(introuvables)))

    # ── Les marchés ──

    def contrats(self):
        from app.models import Contract, Software
        editeurs = self._lire_map('supplier')
        logiciels = self._lire_map('software')
        deja = self._lire_map('contrat')
        for r in self._rows('contrats'):
            if r['id'] in deja:
                continue
            nom = _txt(r.get('libelle'), 128) or _txt(r.get('reference_marche'), 128) \
                or f"Marché #{r['id']}"
            c = Contract(
                name=nom,
                kind=KIND_CONTRAT.get(r.get('nature'), 'maintenance'),
                nature=_txt(r.get('nature'), 16),
                supplier_id=editeurs.get(r.get('fournisseur_id')),
                reference=_txt(r.get('reference_marche'), 128),
                supplier_reference=_txt(r.get('reference_fournisseur'), 128),
                cost_yearly=_dec(r.get('montant_annuel')),
                cost_max_yearly=_dec(r.get('montant_maxi')),
                cost_total=_dec(r.get('montant_total')),
                start_date=r.get('date_debut'),
                end_date=r.get('date_fin'),
                firm_years=r.get('duree_annees'),
                renewals=r.get('renouvellements'),
                renewal_years=r.get('duree_renouvellement'),
                description=_txt(r.get('notes')),
                notice_days=0, priority='medium')
            if self.ecrire:
                self.db.session.add(c)
                self.db.session.flush()
            self._compte('marchés créés')
            self._noter('contrat', r['id'], c.id if self.ecrire else 0)

        # Les logiciels couverts.
        contrats = self._lire_map('contrat')
        for r in self._rows('contrats_logiciels', 'contrat_id, logiciel_id'):
            cid = contrats.get(r['contrat_id'])
            sid = logiciels.get(r['logiciel_id'])
            if not (cid and sid):
                continue
            if not self.ecrire:
                self._compte('logiciels couverts par un marché')
                continue
            c = Contract.query.get(cid)
            sw = Software.query.get(sid)
            if c is not None and sw is not None and sw not in c.software:
                c.software.append(sw)
                self._compte('logiciels couverts par un marché')

    def pieces(self):
        from app.models import ContractItem, CONTRACT_ITEM_KIND_LABELS
        contrats = self._lire_map('contrat')
        deja = self._lire_map('piece')
        for r in self._rows('pieces_contrat'):
            if r['id'] in deja:
                continue
            cid = contrats.get(r['contrat_id'])
            if not cid:
                continue
            nature = r.get('type') or 'abonnement'
            # SoftInventory ne nommait pas le poste : la nature en tient lieu,
            # et l'inventer serait pire que de la reprendre telle quelle.
            item = ContractItem(
                contract_id=cid, kind=nature,
                label=CONTRACT_ITEM_KIND_LABELS.get(nature, nature)[:128],
                cost_yearly=_dec(r.get('cout_annuel')),
                doc_date=r.get('date_piece'))
            if self.ecrire:
                self.db.session.add(item)
                self.db.session.flush()
            self._compte('pièces de marché')
            self._noter('piece', r['id'], item.id if self.ecrire else 0)

    # ── La mise en concurrence ──

    def consultations(self):
        from app.models import Consultation, Quote
        logiciels = self._lire_map('software')
        editeurs = self._lire_map('supplier')
        deja = self._lire_map('consultation')
        for r in self._rows('consultations'):
            if r['id'] in deja:
                continue
            sid = logiciels.get(r['logiciel_id'])
            if not sid:
                continue
            c = Consultation(software_id=sid, subject=(r['objet'] or '')[:256],
                             date=r.get('date'))
            if self.ecrire:
                self.db.session.add(c)
                self.db.session.flush()
            self._compte('consultations')
            self._noter('consultation', r['id'], c.id if self.ecrire else 0)

        consultations = self._lire_map('consultation')
        deja = self._lire_map('devis')
        for r in self._rows('devis'):
            if r['id'] in deja:
                continue
            cid = consultations.get(r['consultation_id'])
            if not cid:
                continue
            q = Quote(consultation_id=cid,
                      supplier_id=editeurs.get(r.get('fournisseur_id')),
                      amount=_dec(r.get('montant')), date=r.get('date'),
                      selected=bool(r.get('retenu')))
            if self.ecrire:
                self.db.session.add(q)
                self.db.session.flush()
            self._compte('devis')
            self._noter('devis', r['id'], q.id if self.ecrire else 0)

    # ── Les certificats électroniques ──

    def certificats(self):
        from app.models import Certificate, UserService, CERT_VALIDITY_LABELS
        editeurs = self._lire_map('supplier')
        services = self._lire_map('service')
        deja = self._lire_map('certificat')
        sans_echeance = []
        for r in self._rows('certificats'):
            if r['id'] in deja:
                continue
            if r.get('date_fin') is None:
                # La fiche entre QUAND MEME, sans date : elle passera en orange,
                # « à compléter ». La refuser perdrait ce qu'on en sait — le
                # titulaire, l'autorité, le bon de commande et sa pièce jointe.
                sans_echeance.append(r.get('titulaire') or f"#{r['id']}")
            sv_id = services.get(r.get('service_id'))
            # Le nom de la fiche : SoftInventory n'en avait pas, le service du
            # titulaire en tient lieu.
            intitule = 'Certificat électronique'
            if sv_id:
                sv = UserService.query.get(sv_id)
                if sv is not None:
                    intitule = sv.name
            statut = r.get('statut')
            c = Certificate(
                kind='signature', service_name=intitule[:128],
                supplier_id=editeurs.get(r.get('fournisseur_id')),
                service_id=sv_id,
                civility=_txt(r.get('civilite'), 8),
                first_name=_txt(r.get('prenom'), 128),
                holder=_txt(r.get('titulaire'), 128),
                holder_role=_txt(r.get('fonction'), 128),
                holder_email=_txt(r.get('email'), 120),
                cert_usage=_txt(r.get('usage'), 24),
                support=_txt(r.get('support'), 16),
                level=_txt(r.get('niveau'), 64),
                serial_number=_txt(r.get('numero_serie'), 128),
                issued_at=r.get('date_debut'), expiry_date=r.get('date_fin'),
                duration_years=r.get('duree_annees'),
                amount_ttc=_dec(r.get('montant_ttc')),
                budget_code=_txt(r.get('imputation'), 32),
                order_signed_on=r.get('bon_commande_le'),
                revocation_code=_txt(r.get('code_revocation'), 64),
                validity=statut if statut in CERT_VALIDITY_LABELS else 'valide',
                description=_txt(r.get('notes')), priority='medium')
            if self.ecrire:
                self.db.session.add(c)
                self.db.session.flush()
            self._compte('certificats électroniques')
            self._noter('certificat', r['id'], c.id if self.ecrire else 0)
        if sans_echeance:
            self.avertissements.append(
                'Certificats repris SANS date de fin, à compléter (ils paraissent '
                'en orange et ne déclenchent pas d\'alerte) : '
                + ', '.join(sans_echeance))

    # ── Liaisons et partages ──

    def liaisons(self):
        from app.models import SoftwareLink, SoftwareShare
        logiciels = self._lire_map('software')

        deja = self._lire_map('interconnexion')
        for r in self._rows('interconnexions'):
            if r['id'] in deja:
                continue
            src = logiciels.get(r['source_id'])
            cible = logiciels.get(r['cible_id'])
            if not (src and cible) or src == cible:
                continue
            if self.ecrire and SoftwareLink.query.filter_by(
                    source_id=src, target_id=cible).first():
                self._compte('flux déjà présents')
                continue
            lien = SoftwareLink(source_id=src, target_id=cible,
                                description=_txt(r.get('description'), 256))
            if self.ecrire:
                self.db.session.add(lien)
                self.db.session.flush()
            self._compte('flux entre logiciels')
            self._noter('interconnexion', r['id'], lien.id if self.ecrire else 0)

        deja = self._lire_map('partage')
        for r in self._rows('partages_logiciel'):
            if r['id'] in deja:
                continue
            sid = logiciels.get(r['logiciel_id'])
            if not sid:
                continue
            chemin = (r['chemin'] or '')[:512]
            if self.ecrire and SoftwareShare.query.filter_by(
                    software_id=sid, path=chemin).first():
                self._compte('dossiers déjà présents')
                continue
            p = SoftwareShare(software_id=sid, path=chemin,
                              label=_txt(r.get('libelle'), 128))
            if self.ecrire:
                self.db.session.add(p)
                self.db.session.flush()
            self._compte('dossiers du partage réseau')
            self._noter('partage', r['id'], p.id if self.ecrire else 0)

    # ── Les pièces jointes ──

    def documents(self, avec_contenu=True):
        from app.models import Document, DocumentContent
        parents = {
            'logiciel_id': ('software_id', self._lire_map('software')),
            'editeur_id': ('supplier_id', self._lire_map('supplier')),
            'piece_contrat_id': ('contract_item_id', self._lire_map('piece')),
            'devis_id': ('quote_id', self._lire_map('devis')),
            'certificat_id': ('certificate_id', self._lire_map('certificat')),
        }
        categories = self._lire_map('doc_category')
        deja = self._lire_map('document')
        orphelins = []
        for r in self._rows('documents'):
            if r['id'] in deja:
                continue
            champ = valeur = None
            for colonne, (attr, table) in parents.items():
                if r.get(colonne):
                    champ, valeur = attr, table.get(r[colonne])
                    break
            if not champ or not valeur:
                orphelins.append(r.get('nom_original') or f"#{r['id']}")
                continue
            doc = Document(filename=(r['nom_original'] or 'piece-jointe')[:256],
                           mime=_txt(r.get('mime'), 128), size=r.get('taille'),
                           uploaded_by=_txt(r.get('depose_par_label'), 64),
                           category_id=categories.get(r.get('categorie_id')))
            setattr(doc, champ, valeur)
            if avec_contenu and self.ecrire:
                # Le contenu se lit à la ligne, pas en bloc : 630 Mo de pièces
                # jointes chargés d'un coup n'ont aucune raison de tenir en
                # mémoire tous en même temps.
                self.cur.execute(
                    'SELECT contenu FROM documents_contenu WHERE document_id = %s',
                    (r['id'],))
                ligne = self.cur.fetchone()
                if ligne is not None:
                    doc.content = DocumentContent(data=bytes(ligne['contenu']))
            if self.ecrire:
                self.db.session.add(doc)
                self.db.session.flush()
                # On valide au fil de l'eau : une transaction de 630 Mo tiendrait
                # tout en mémoire jusqu'au bout, et une erreur sur la dernière
                # pièce perdrait les 438 autres.
                if self.rapport.get('pièces jointes', 0) % 25 == 24:
                    self.db.session.commit()
            self._compte('pièces jointes')
            self._noter('document', r['id'], doc.id if self.ecrire else 0)
        if orphelins:
            self.avertissements.append(
                'Pièces jointes dont la fiche parente n\'a pas été reprise : '
                + ', '.join(orphelins[:20])
                + (f' … ({len(orphelins)} au total)' if len(orphelins) > 20 else ''))


def main():
    # La console Windows repond en cp1252 : sans cela, un rapport en francais
    # se termine par une erreur d'encodage apres avoir tout fait.
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dsn', default=DSN_DEFAUT,
                    help=f'Base PostgreSQL source (défaut : {DSN_DEFAUT})')
    ap.add_argument('--base',
                    help="Base Sentinelle à alimenter (défaut : celle du .env)")
    ap.add_argument('--essai', action='store_true',
                    help="Lit et compte sans rien écrire")
    ap.add_argument('--sans-documents', action='store_true',
                    help="Reprend les fiches de pièces jointes sans leur contenu")
    ap.add_argument('--sans-creer-serveurs', action='store_true',
                    help="N'ajoute rien au parc : les serveurs sans jumeau sont "
                         "seulement nommés, et leurs installations non posées")
    args = ap.parse_args()

    import psycopg
    from psycopg.rows import dict_row

    from config import Config
    from app import create_app, db

    class C(Config):
        pass
    if args.base:
        # Une base VISEE explicitement : on remet a plat une copie rapatriee
        # d'un serveur sans toucher a celle du poste.
        C.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.abspath(args.base)

    app = create_app(C)
    with app.app_context(), psycopg.connect(args.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            r = Reprise(cur, db, ecrire=not args.essai,
                        creer_serveurs=not args.sans_creer_serveurs)
            r.services()
            r.referentiels()
            r.editeurs()
            r.logiciels()
            r.logiciels_services()
            r.logiciels_serveurs()
            r.contrats()
            r.pieces()
            r.consultations()
            r.certificats()
            r.liaisons()
            r.documents(avec_contenu=not args.sans_documents)
            if r.ecrire:
                db.session.commit()
            else:
                # L'essai lit la base de Sentinelle pour rapprocher les fiches ;
                # il a donc pu modifier des objets en memoire. On defait tout
                # explicitement plutot que de compter sur la fermeture du
                # contexte : « rien ecrit » doit etre vrai sans avoir a le
                # demontrer.
                db.session.rollback()

    print()
    print('== Reprise SoftInventory ' + ('(ESSAI, rien ecrit) ' if args.essai else '')
          + '=' * 20)
    print('  Base :', app.config['SQLALCHEMY_DATABASE_URI'])
    for quoi, n in sorted(r.rapport.items()):
        print(f'  {n:>6}  {quoi}')
    if not r.rapport:
        print('  Rien à reprendre.')
    for a in r.avertissements:
        print()
        print('  /!\ ' + a)
    print()


if __name__ == '__main__':
    main()
