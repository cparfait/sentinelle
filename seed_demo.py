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
                        TestTask, AccessReview, SystemUpdate)

TAG = '[démo]'
TODAY = date.today()


def d(offset_days):
    """Date relative a aujourd'hui (offset negatif = passe)."""
    return TODAY + timedelta(days=offset_days)


def purge():
    n = 0
    for model, field in [(Account, 'description'), (Certificate, 'description'),
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
        ('SRV-AD01', 'server', f'Contrôleur de domaine principal {TAG}'),
        ('SRV-FILE01', 'server', f'Serveur de fichiers {TAG}'),
        ('SRV-WEB01', 'server', f'Reverse proxy / web {TAG}'),
        ('SRV-HYPERV01', 'server', f'Hôte de virtualisation {TAG}'),
        ('SRV-SQL01', 'server', f'Base de donnees SQL {TAG}'),
    ]
    for name, atype, desc in assets:
        db.session.add(Asset(name=name, asset_type=atype, description=desc))

    # --- Comptes a rotation de mot de passe ---
    accounts = [
        ('Active Directory', 'svc-backup', 'ldap://srv-ad01', -100, 90, 'high'),
        ('OVH Manager', 'dsi@chatillon92.fr', 'https://ovh.com', -85, 90, 'high'),
        ('Switch Cisco core', 'admin', None, -200, 180, 'medium'),
        ('NAS Synology', 'admin', 'https://nas.local:5001', -30, 90, 'medium'),
        ('Compte Microsoft 365', 'admin@chatillon92.fr', 'https://portal.office.com', -10, 60, 'high'),
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
        ('Site municipal', 'www.chatillon92.fr', "Let's Encrypt", 5, True, 'high'),
        ('Portail famille', 'famille.chatillon92.fr', "Let's Encrypt", 20, True, 'high'),
        ('Webmail', 'mail.chatillon92.fr', 'Sectigo', 45, False, 'medium'),
        ('Intranet', 'intranet.chatillon92.fr', 'CA interne', -3, False, 'high'),
        ('VPN SSL', 'vpn.chatillon92.fr', 'DigiCert', 120, False, 'medium'),
    ]
    for svc, dom, issuer, exp_off, auto, prio in certs:
        db.session.add(Certificate(
            service_name=svc, domain=dom, issuer=issuer, issued_at=d(-300),
            expiry_date=d(exp_off), auto_renew=auto, priority=prio,
            description=f'Certificat TLS {TAG}'))

    # --- Noms de domaine ---
    domains = [
        ('chatillon92.fr', 'OVH', 40, True, 'high'),
        ('ville-chatillon.fr', 'Gandi', 200, True, 'medium'),
        ('chatillon-tourisme.fr', 'OVH', 15, False, 'high'),
        ('chatillon92.com', 'Gandi', -5, False, 'low'),
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
