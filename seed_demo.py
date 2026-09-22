"""Remplit Sentinelle de donnees fictives pour tester l'application.

Usage :
    .\\venv\\Scripts\\python.exe seed_demo.py          # ajoute les donnees demo
    .\\venv\\Scripts\\python.exe seed_demo.py --reset    # supprime puis recree

Les enregistrements demo sont marques par « [démo] » dans leur description,
ce qui permet de les retrouver et de les purger sans toucher aux vraies donnees.
"""
import sys
from datetime import date, timedelta, datetime, timezone

from app import create_app, db
from app.models import (Asset, Account, Certificate, Domain, Backup, BackupCheck,
                        TestTask, AccessReview, SystemUpdate, Supplier, Contract,
                        Software, Equipment)

TAG = '[démo]'
TODAY = date.today()


def d(offset_days):
    """Date relative a aujourd'hui (offset negatif = passe)."""
    return TODAY + timedelta(days=offset_days)


def purge():
    n = 0
    # Les contrats d'abord : ils referencent fournisseurs, logiciels et materiel.
    for model, field in [(Contract, 'description'), (Software, 'description'),
                         (Equipment, 'observations'), (Supplier, 'notes'),
                         (Account, 'description'), (Certificate, 'description'),
                         (Domain, 'description'), (Backup, 'description'),
                         (TestTask, 'description'), (AccessReview, 'scope'),
                         (SystemUpdate, 'description'), (Asset, 'description')]:
        col = getattr(model, field)
        rows = model.query.filter(col.ilike(f'%{TAG}%')).all()
        for r in rows:
            db.session.delete(r)
            n += 1
    db.session.commit()
    return n


def seed():
    # --- Catalogue d'actifs (applications / serveurs) ---
    assets = [
        ('GLPI', 'application', f'Gestion de parc et ITSM {TAG}'),
        ('SIRH', 'application', f'Ressources humaines {TAG}'),
        ('GED Maarch', 'application', f'Gestion electronique de documents {TAG}'),
        ('Finances Berger-Levrault', 'application', f'Comptabilite publique {TAG}'),
        ('Portail famille', 'application', f'Inscriptions periscolaires {TAG}'),
        ('SRV-AD01', 'divers', f'Contrôleur de domaine principal {TAG}'),
        ('SRV-FILE01', 'divers', f'Serveur de fichiers {TAG}'),
        ('SRV-WEB01', 'divers', f'Reverse proxy / web {TAG}'),
        ('SRV-HYPERV01', 'divers', f'Hôte de virtualisation {TAG}'),
        ('SRV-SQL01', 'divers', f'Base de donnees SQL {TAG}'),
    ]
    for name, atype, desc in assets:
        db.session.add(Asset(name=name, asset_type=atype, description=desc))

    # --- Comptes a rotation de mot de passe ---
    accounts = [
        ('Active Directory', 'svc-backup', 'ldap://srv-ad01', -100, 90, 'high'),
        ('OVH Manager', 'dsi@collectivite.fr', 'https://ovh.com', -85, 90, 'high'),
        ('Switch Cisco core', 'admin', None, -200, 180, 'medium'),
        ('NAS Synology', 'admin', 'https://nas.local:5001', -30, 90, 'medium'),
        ('Compte Microsoft 365', 'admin@collectivite.fr', 'https://portal.office.com', -10, 60, 'high'),
        ('Firewall Stormshield', 'admin', 'https://fw.local', -60, 90, 'high'),
        ('GLPI superadmin', 'glpi', 'https://glpi.local', -5, 120, 'low'),
    ]
    for svc, user, url, last_off, rot, prio in accounts:
        last = d(last_off)
        db.session.add(Account(
            service_name=svc, username=user, url=url, rotation_days=rot,
            last_password_change=last, next_password_change=last + timedelta(days=rot),
            priority=prio, description=f'Compte de service {TAG}'))

    # --- Certificats TLS ---
    certs = [
        ('Site municipal', 'www.collectivite.fr', "Let's Encrypt", 5, True, 'high'),
        ('Portail famille', 'famille.collectivite.fr', "Let's Encrypt", 20, True, 'high'),
        ('Webmail', 'mail.collectivite.fr', 'Sectigo', 45, False, 'medium'),
        ('Intranet', 'intranet.collectivite.fr', 'CA interne', -3, False, 'high'),
        ('VPN SSL', 'vpn.collectivite.fr', 'DigiCert', 120, False, 'medium'),
    ]
    for svc, dom, issuer, exp_off, auto, prio in certs:
        db.session.add(Certificate(
            service_name=svc, domain=dom, issuer=issuer, issued_at=d(-300),
            expiry_date=d(exp_off), auto_renew=auto, priority=prio,
            description=f'Certificat TLS {TAG}'))

    # --- Noms de domaine ---
    domains = [
        ('collectivite.fr', 'OVH', 40, True, 'high'),
        ('ville-collectivite.fr', 'Gandi', 200, True, 'medium'),
        ('collectivite-tourisme.fr', 'OVH', 15, False, 'high'),
        ('collectivite92.com', 'Gandi', -5, False, 'low'),
    ]
    for name, reg, exp_off, auto, prio in domains:
        db.session.add(Domain(name=name, registrar=reg, expiry_date=d(exp_off),
                              auto_renew=auto, priority=prio,
                              description=f'Nom de domaine {TAG}'))

    # --- Sauvegardes + historique de checks ---
    backups = [
        ('Veeam - VMs production', 'incremental', 'Repository NAS', 'daily', '22:00', 'high'),
        ('Sauvegarde AD', 'full', 'Bande LTO', 'weekly', '23:30', 'high'),
        ('Fichiers partagés', 'differential', 'NAS Synology', 'daily', '21:00', 'medium'),
        ('Base SQL Finances', 'full', 'SRV-SQL01', 'daily', '01:00', 'high'),
        ('Snapshots Hyper-V', 'snapshot', 'SAN', 'daily', '03:00', 'medium'),
    ]
    import random
    random.seed(42)
    for i, (svc, btype, loc, freq, time, prio) in enumerate(backups):
        b = Backup(service_name=svc, backup_type=btype, location=loc, frequency=freq,
                   expected_time=time, priority=prio, description=f'Job de sauvegarde {TAG}')
        db.session.add(b)
        db.session.flush()  # pour avoir b.id
        # 25 jours de checks (surtout OK, quelques warning/echec)
        for off in range(25, 0, -1):
            r = random.random()
            if i == 3 and off <= 2:      # SQL : echec recent
                status = 'failed'
            elif r < 0.08:
                status = 'failed'
            elif r < 0.18:
                status = 'warning'
            else:
                status = 'ok'
            db.session.add(BackupCheck(
                backup_id=b.id, check_date=d(-off), status=status,
                comment=('Espace disque faible' if status == 'warning' else
                         ('Job en erreur' if status == 'failed' else None)),
                checked_by='demo',
                checked_at=datetime.now(timezone.utc) - timedelta(days=off)))

    # --- Tests recurrents ---
    tests = [
        ('Restauration Veeam', 'restauration', -80, 90, 'completed', 'high'),
        ('Test PRA basculement', 'pra', -200, 180, 'pending', 'high'),
        ('Test envoi alerte mail', 'alerte', -10, 30, 'completed', 'low'),
        ('Bascule onduleur', 'onduleur', -120, 90, 'failed', 'medium'),
        ('Test sauvegarde SQL', 'restauration', -25, 30, 'pending', 'high'),
    ]
    for name, ttype, last_off, freq, status, prio in tests:
        last = d(last_off)
        db.session.add(TestTask(
            name=name, test_type=ttype, last_performed=last,
            next_due=last + timedelta(days=freq), frequency_days=freq,
            status=status, priority=prio,
            result=('OK' if status == 'completed' else None),
            description=f'Test recurrent {TAG}'))

    # --- Revues de droits (applications metier) ---
    reviews = [
        ('SIRH', 'DRH', -300, 365, 'completed', 'high'),
        ('Finances Berger-Levrault', 'DAF', -30, 365, 'pending', 'high'),
        ('GED Maarch', 'Secrétariat général', -400, 365, 'pending', 'medium'),
        ('GLPI', 'DSI', -90, 180, 'completed', 'low'),
    ]
    for app_name, resp, last_off, freq, status, prio in reviews:
        last = d(last_off)
        db.session.add(AccessReview(
            application=app_name, responsible=resp, frequency_days=freq,
            last_review=last, next_review=last + timedelta(days=freq),
            status=status, priority=prio,
            scope=f'Revue des comptes et profils {TAG}'))

    # --- Mises a jour applications / systemes ---
    updates = [
        ('GLPI', 'application', '10.0.10', '10.0.14', 'update_available', 'interne', 'Jean Martin (DSI)', 'medium'),
        ('Windows Server 2022', 'system', '21H2', '21H2', 'up_to_date', 'interne', 'Équipe infra', 'medium'),
        ('Nginx SRV-WEB01', 'system', '1.24.0', '1.27.0', 'critical', 'interne', None, 'high'),
        ('SIRH', 'application', '2024.1', '2024.3', 'update_available', 'prestataire', 'Société RH-Soft', 'high'),
        ('VMware ESXi', 'system', '7.0U3', '8.0U2', 'update_available', 'prestataire', 'IntégrateurX', 'medium'),
        ('Maarch GED', 'application', '21.03', '21.03', 'up_to_date', 'prestataire', 'Maarch', 'low'),
    ]
    for name, stype, cur, latest, status, utype, by, prio in updates:
        db.session.add(SystemUpdate(
            name=name, system_type=stype, current_version=cur, latest_version=latest,
            status=status, updater_type=utype, updated_by=by,
            last_update=d(-40) if status == 'up_to_date' else None,
            priority=prio, description=f'Suivi de version {TAG}'))

    # --- Fournisseurs ---
    suppliers = {}
    for name, kind, contact, support_phone, email, url in [
        ('Berger-Levrault', 'editor', 'Sophie Lambert', '01 23 45 67 01', 'support@exemple-bl.fr', 'https://support.exemple-bl.fr'),
        ('Maarch', 'editor', 'Paul Girard', '01 23 45 67 02', 'support@exemple-maarch.fr', None),
        ('RH-Soft', 'editor', 'Claire Morel', '01 23 45 67 03', 'hotline@exemple-rhsoft.fr', 'https://rhsoft.exemple.fr/tickets'),
        ('Dell Technologies', 'manufacturer', None, '0 800 00 00 04', None, 'https://www.dell.com/support'),
        ('IntégrateurX', 'provider', 'Marc Petit', '01 23 45 67 05', 'contact@exemple-integx.fr', None),
        ('Orange Business', 'operator', 'Service client entreprises', '3901', None, None),
        ('OVHcloud', 'provider', None, '1007', None, 'https://help.ovhcloud.com'),
    ]:
        sup = Supplier(name=name, kind=kind, contact_name=contact, support_phone=support_phone,
                       email=email, support_url=url, notes=f'Fournisseur fictif {TAG}')
        db.session.add(sup)
        suppliers[name] = sup
    db.session.flush()

    # --- Materiel (serveurs, stockage, reseau) ---
    equipments = {}
    for kind, name, env, crit, os_, ver, os_upd, ip, model, warranty, sup in [
        ('physical', 'SRV-HYPERV01', 'prod', 4, 'Windows Server', '2022', -20, '10.0.1.10', 'Dell PowerEdge R750', 400, 'Dell Technologies'),
        ('physical', 'SRV-HYPERV02', 'prod', 4, 'Windows Server', '2019', -500, '10.0.1.11', 'Dell PowerEdge R740', 25, 'Dell Technologies'),
        ('vm', 'SRV-AD01', 'prod', 4, 'Windows Server', '2022', -15, '10.0.2.10', None, None, None),
        ('vm', 'SRV-FILE01', 'prod', 3, 'Windows Server', '2019', -60, '10.0.2.20', None, None, None),
        ('vm', 'SRV-SQL01', 'prod', 4, 'Windows Server', '2019', -420, '10.0.2.30', None, None, None),
        ('vm', 'SRV-WEB01', 'prod', 3, 'Debian', '12', -10, '10.0.3.10', None, None, None),
        ('vm', 'SRV-GLPI-TEST', 'preprod', 1, 'Debian', '11', -200, '10.0.9.10', None, None, None),
        ('nas', 'NAS-SAUVEGARDE', 'prod', 3, 'DSM', '7.2', -90, '10.0.1.50', 'Synology RS2423+', 700, None),
        ('network', 'FW-CORE', 'prod', 4, 'SNS', '4.8', -45, '10.0.0.1', 'Stormshield SN910', 55, 'IntégrateurX'),
        ('network', 'SW-CORE-01', 'prod', 4, 'IOS-XE', '17.9', -300, '10.0.0.2', 'Cisco Catalyst 9300', -10, 'IntégrateurX'),
    ]:
        eq = Equipment(kind=kind, name=name, environment=env, criticality=crit, os=os_,
                       os_version=ver, os_last_update=d(os_upd), ip_address=ip,
                       manufacturer_model=model,
                       warranty_end=d(warranty) if warranty is not None else None,
                       supplier=suppliers.get(sup), observations=f'Équipement fictif {TAG}')
        db.session.add(eq)
        equipments[name] = eq

    # --- Logiciels ---
    softwares = {}
    for name, sup, ver, hosting, lifecycle, auth, users, crit, gdpr, resp in [
        ('Finances BL', 'Berger-Levrault', '2024.2', 'on_premise', 'production', 'ldap', 45, 4, True, 'DAF'),
        ('GED Maarch', 'Maarch', '21.03', 'on_premise', 'production', 'ldap', 120, 3, True, 'Secrétariat général'),
        ('SIRH', 'RH-Soft', '2024.3', 'saas', 'production', 'sso', 30, 4, True, 'DRH'),
        ('Portail famille', 'Berger-Levrault', '5.1', 'saas', 'production', 'locale', 2500, 3, True, 'Direction enfance'),
        ('GLPI', None, '10.0.14', 'on_premise', 'production', 'ldap', 12, 2, False, 'DSI'),
        ('Ancien logiciel cimetières', None, '3.2', 'on_premise', 'fin_de_vie', 'locale', 3, 2, True, 'État civil'),
        ('Outil de sondage en ligne', None, None, 'saas', 'evaluation', 'sso', None, 1, False, 'Communication'),
    ]:
        sw = Software(name=name, supplier=suppliers.get(sup), version=ver, hosting=hosting,
                      lifecycle=lifecycle, auth_mode=auth, users_count=users, criticality=crit,
                      gdpr_personal_data=gdpr, responsible=resp,
                      description=f'Logiciel fictif {TAG}')
        db.session.add(sw)
        softwares[name] = sw
    db.session.flush()

    # --- Contrats (echeances variees : depassee, proche, lointaine) ---
    for name, kind, nature, sup, cost, start, end, notice, auto, eqs, sws in [
        ('Maintenance Finances BL', 'maintenance', 'marche', 'Berger-Levrault', 18500, -1000, 60, 90, False, [], ['Finances BL', 'Portail famille']),
        ('Abonnement SIRH', 'subscription', 'marche', 'RH-Soft', 24000, -700, 400, 180, False, [], ['SIRH']),
        ('Support GED Maarch', 'maintenance', 'contrat', 'Maarch', 6200, -300, 20, 30, True, [], ['GED Maarch']),
        ('Garantie serveurs Dell', 'maintenance', 'contrat', 'Dell Technologies', 3900, -1100, 25, 0, False, ['SRV-HYPERV01', 'SRV-HYPERV02'], []),
        ('Infogérance réseau', 'maintenance', 'marche', 'IntégrateurX', 15000, -800, -15, 60, False, ['FW-CORE', 'SW-CORE-01'], []),
        ('Liens fibre et téléphonie', 'subscription', 'marche', 'Orange Business', 32000, -900, 250, 90, True, [], []),
        ('Hébergement DNS et domaines', 'subscription', 'contrat', 'OVHcloud', 450, -400, 330, 0, True, [], []),
    ]:
        c = Contract(name=name, kind=kind, nature=nature, supplier=suppliers[sup],
                     cost_yearly=cost, start_date=d(start), end_date=d(end),
                     notice_days=notice, auto_renew=auto, description=f'Contrat fictif {TAG}')
        c.equipments = [equipments[n] for n in eqs]
        c.software = [softwares[n] for n in sws]
        db.session.add(c)

    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        if '--reset' in sys.argv:
            print('Purge des donnees demo existantes :', purge(), 'enregistrement(s)')
        already = Account.query.filter(Account.description.ilike(f'%{TAG}%')).first()
        if already and '--reset' not in sys.argv:
            print("Des donnees demo existent deja. Relancez avec --reset pour les recreer.")
        else:
            seed()
            print('Donnees fictives creees :')
            print(' -', Asset.query.count(), 'actifs |', Account.query.count(), 'comptes |',
                  Certificate.query.count(), 'certificats |', Domain.query.count(), 'domaines')
            print(' -', Backup.query.count(), 'backups |', BackupCheck.query.count(), 'checks |',
                  TestTask.query.count(), 'tests |', AccessReview.query.count(), 'revues |',
                  SystemUpdate.query.count(), 'mises a jour')
            print(' -', Supplier.query.count(), 'fournisseurs |', Contract.query.count(), 'contrats |',
                  Software.query.count(), 'logiciels |', Equipment.query.count(), 'equipements')
