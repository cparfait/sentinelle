from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from app import db
from app.models import (Account, Certificate, Backup, BackupCheck, TestTask, Domain,
                        AccessReview, SystemUpdate)
from app.alerts import send_alert
from app.snooze import is_snoozed

scheduler = BackgroundScheduler()

# Application Flask conservee pour fournir un contexte aux jobs planifies.
# On NE recree PAS l'app dans chaque job : cela relancait db.create_all(),
# le seed de l'admin et le scheduler lui-meme (-> ConflictingIdError).
_app = None


def check_passwords():
    with _app.app_context():
        today = datetime.now(timezone.utc).date()
        accounts = Account.query.filter_by(is_active=True).all()
        for account in accounts:
            if not account.next_password_change:
                continue
            if is_snoozed('account', account.id):
                continue
            days_left = (account.next_password_change - today).days
            if days_left in (30, 15, 7, 3, 1, 0):
                urgency = 'EXPIRÉ' if days_left <= 0 else f'expire dans {days_left} jour(s)'
                subject = f"Alerte mot de passe - {account.service_name}"
                body = (
                    f"Le mot de passe du compte suivant {urgency}:\n\n"
                    f"Service: {account.service_name}\n"
                    f"Utilisateur: {account.username}\n"
                    f"Prochain changement: {account.next_password_change.strftime('%d/%m/%Y')}\n"
                    f"Jours restants: {days_left}\n"
                )
                send_alert(subject, body, 'account', account.id,
                           f'{account.service_name} ({account.username})')


def check_certificates():
    with _app.app_context():
        today = datetime.now(timezone.utc).date()
        certs = Certificate.query.filter_by(is_active=True).all()
        for cert in certs:
            if is_snoozed('certificate', cert.id):
                continue
            days_left = (cert.expiry_date - today).days
            if days_left in (30, 15, 7, 3, 1, 0, -1):
                urgency = 'EXPIRÉ' if days_left < 0 else f'expire dans {days_left} jour(s)'
                subject = f"Alerte certificat - {cert.domain}"
                body = (
                    f"Le certificat suivant {urgency}:\n\n"
                    f"Service: {cert.service_name}\n"
                    f"Domaine: {cert.domain}\n"
                    f"Émetteur: {cert.issuer}\n"
                    f"Date d'expiration: {cert.expiry_date.strftime('%d/%m/%Y')}\n"
                    f"Jours restants: {days_left}\n"
                    f"Auto-renouvellement: {'Oui' if cert.auto_renew else 'Non'}\n"
                )
                send_alert(subject, body, 'certificate', cert.id,
                           f'{cert.service_name} - {cert.domain}')


def check_backups():
    with _app.app_context():
        backups = Backup.query.filter_by(is_active=True).all()
        for backup in backups:
            # On s'appuie sur la logique reelle du modele (BackupCheck quotidiens),
            # et non sur des champs status/last_run qui n'existent pas.
            if backup.computed_status() != 'danger':
                continue
            if is_snoozed('backup', backup.id):
                continue
            today_check = backup.today_check()
            last_ok = backup.last_ok_check()
            days_since = backup.days_since_last_ok()
            if today_check and today_check.status == 'failed':
                detail = f"Le check du jour est en ECHEC ({today_check.comment or 'sans commentaire'})"
            elif last_ok:
                detail = (
                    f"Dernier backup OK le {last_ok.check_date.strftime('%d/%m/%Y')} "
                    f"(il y a {days_since} j ; cadence attendue : "
                    f"{backup.frequency_label().lower()} / {backup.expected_interval_days()} j)"
                )
            else:
                detail = "Aucun backup OK enregistre pour ce service"

            subject = f"Alerte backup - {backup.service_name}"
            body = (
                f"Le backup suivant necessite une attention:\n\n"
                f"Service: {backup.service_name}\n"
                f"Type: {backup.backup_type}\n"
                f"Emplacement: {backup.location}\n"
                f"Frequence: {backup.frequency_label()}\n"
                f"{detail}\n"
            )
            send_alert(subject, body, 'backup', backup.id, backup.service_name)


def check_tests():
    with _app.app_context():
        today = datetime.now(timezone.utc).date()
        tests = TestTask.query.filter_by(is_active=True).all()
        for test in tests:
            if is_snoozed('test', test.id):
                continue
            if not test.next_due:
                continue
            days_left = (test.next_due - today).days
            if days_left in (7, 3, 1, 0):
                urgency = 'EN RETARD' if days_left < 0 else f'prévu dans {days_left} jour(s)'
                subject = f"Alerte test - {test.name}"
                body = (
                    f"Le test suivant est {urgency}:\n\n"
                    f"Nom: {test.name}\n"
                    f"Type: {test.test_type}\n"
                    f"Date prévue: {test.next_due.strftime('%d/%m/%Y')}\n"
                    f"Jours restants: {days_left}\n"
                )
                send_alert(subject, body, 'test', test.id, test.name)


def check_domains():
    with _app.app_context():
        today = datetime.now(timezone.utc).date()
        for domain in Domain.query.filter_by(is_active=True).all():
            if not domain.expiry_date or is_snoozed('domain', domain.id):
                continue
            days_left = (domain.expiry_date - today).days
            if days_left in (90, 60, 30, 15, 7, 3, 1, 0, -1):
                urgency = 'EXPIRÉ' if days_left < 0 else f'expire dans {days_left} jour(s)'
                subject = f"Alerte domaine - {domain.name}"
                body = (
                    f"Le nom de domaine suivant {urgency}:\n\n"
                    f"Domaine: {domain.name}\n"
                    f"Registrar: {domain.registrar or 'N/A'}\n"
                    f"Date d'expiration: {domain.expiry_date.strftime('%d/%m/%Y')}\n"
                    f"Jours restants: {days_left}\n"
                    f"Renouvellement auto: {'Oui' if domain.auto_renew else 'Non'}\n"
                )
                send_alert(subject, body, 'domain', domain.id, domain.name)


def refresh_domains_rdap():
    """Lit en direct l'expiration RDAP de chaque domaine actif."""
    with _app.app_context():
        from app.domains import refresh_domain_rdap
        for domain in Domain.query.filter_by(is_active=True).all():
            try:
                refresh_domain_rdap(domain, 'auto-rdap')
                db.session.commit()
            except Exception:
                db.session.rollback()


def sync_ad_passwords():
    """Synchronise l'expiration des mots de passe depuis l'AD (compte de service)."""
    with _app.app_context():
        from app.ldap_auth import sync_password_expirations
        try:
            updated, errors = sync_password_expirations()
            _app.logger.info('Synchro AD : %s compte(s) mis a jour, %s erreur(s)',
                             updated, len(errors))
        except Exception as e:
            _app.logger.error('Echec synchro AD : %s', e)


def check_reviews():
    with _app.app_context():
        today = datetime.now(timezone.utc).date()
        for review in AccessReview.query.filter_by(is_active=True).all():
            if not review.next_review or is_snoozed('review', review.id):
                continue
            days_left = (review.next_review - today).days
            if days_left in (30, 15, 7, 3, 1, 0):
                urgency = 'EN RETARD' if days_left < 0 else f'prevue dans {days_left} jour(s)'
                subject = f"Alerte revue de droits - {review.application}"
                body = (
                    f"La revue de droits suivante est {urgency}:\n\n"
                    f"Application: {review.application}\n"
                    f"Responsable: {review.responsible or 'N/A'}\n"
                    f"Prochaine revue: {review.next_review.strftime('%d/%m/%Y')}\n"
                    f"Jours restants: {days_left}\n"
                )
                send_alert(subject, body, 'review', review.id, review.application)


def check_updates():
    with _app.app_context():
        for upd in SystemUpdate.query.filter_by(is_active=True).all():
            if upd.status != 'critical' or is_snoozed('update', upd.id):
                continue
            subject = f"Alerte mise a jour critique - {upd.name}"
            body = (
                f"Une mise a jour critique est en attente:\n\n"
                f"Element: {upd.name}\n"
                f"Version actuelle: {upd.current_version or 'N/A'}\n"
                f"Derniere version: {upd.latest_version or 'N/A'}\n"
            )
            send_alert(subject, body, 'update', upd.id, upd.name)


def refresh_certificates_tls():
    """Lit en direct la date d'expiration reelle de chaque certificat actif et
    met a jour les fiches. Tourne avant l'alerte certificats du matin."""
    with _app.app_context():
        from app.certificates import refresh_certificate_tls
        certs = Certificate.query.filter_by(is_active=True).all()
        for cert in certs:
            try:
                refresh_certificate_tls(cert, 'auto-tls')
                db.session.commit()
            except Exception:
                db.session.rollback()


def send_daily_digest():
    """Envoie le recapitulatif quotidien de la meteo DSI (un seul email)."""
    with _app.app_context():
        from flask import current_app
        from app.digest import build_daily_digest
        from app.email_service import send_email
        from app.models import AlertLog

        recipients = [r.strip() for r in _app.config.get('ALERT_RECIPIENTS', [])
                      if r and r.strip()]
        if not recipients:
            return

        base_url = _app.config.get('APP_BASE_URL', '')
        subject, text_body, html_body, _ = build_daily_digest(base_url)
        try:
            send_email(subject, recipients, text_body, html_body=html_body)
            status = 'sent'
            message = text_body
        except Exception as e:
            status = 'failed'
            message = f"ERREUR: {e}\n{text_body}"
        db.session.add(AlertLog(
            alert_type='digest', entity_type='digest', entity_name='Meteo quotidienne',
            message=message, recipients=', '.join(recipients), status=status))
        db.session.commit()


def backup_database_job():
    """Sauvegarde quotidienne de la base SQLite de Sentinelle."""
    with _app.app_context():
        from app.db_backup import backup_database
        try:
            path = backup_database(_app)
            _app.logger.info('Sauvegarde base creee : %s', path)
        except Exception as e:
            _app.logger.error('Echec sauvegarde base : %s', e)


def scan_backup_inbox():
    """Scanne le repertoire des mails de backup et enregistre les checks."""
    with _app.app_context():
        directory = _app.config.get('BACKUP_INBOX_DIR')
        if not directory:
            return
        from app.backup_ingest import scan_inbox
        scan_inbox(directory)


def _on_job_event(event):
    """Enregistre chaque execution de job (succes/erreur) pour diagnostic."""
    if _app is None:
        return
    with _app.app_context():
        from app.models import SchedulerRun
        try:
            db.session.add(SchedulerRun(
                job_id=event.job_id,
                status='error' if event.exception else 'ok',
                message=str(event.exception) if event.exception else None))
            # purge : ne garde que les 500 dernieres executions
            old = SchedulerRun.query.order_by(SchedulerRun.id.desc()).offset(500).all()
            for r in old:
                db.session.delete(r)
            db.session.commit()
        except Exception:
            db.session.rollback()


def start_scheduler(app):
    """Demarre le scheduler avec l'app reelle (sans la recreer dans les jobs)."""
    global _app
    _app = app

    if scheduler.running:
        return

    scheduler.add_listener(_on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    if app.config.get('BACKUP_INBOX_DIR'):
        scheduler.add_job(scan_backup_inbox, 'interval', minutes=30,
                          id='scan_backup_inbox', replace_existing=True)

    scheduler.add_job(backup_database_job, 'cron', hour=1, minute=0,
                      id='backup_database_job', replace_existing=True)

    if app.config.get('LDAP_ENABLED') and app.config.get('LDAP_BIND_USER'):
        scheduler.add_job(sync_ad_passwords, 'cron', hour=6, minute=0,
                          id='sync_ad_passwords', replace_existing=True)
    scheduler.add_job(refresh_certificates_tls, 'cron', hour=7, minute=0,
                      id='refresh_certificates_tls', replace_existing=True)
    scheduler.add_job(refresh_domains_rdap, 'cron', hour=7, minute=10,
                      id='refresh_domains_rdap', replace_existing=True)
    scheduler.add_job(send_daily_digest, 'cron', hour=7, minute=30,
                      id='send_daily_digest', replace_existing=True)
    scheduler.add_job(check_domains, 'cron', hour=8, minute=20,
                      id='check_domains', replace_existing=True)
    scheduler.add_job(check_passwords, 'cron', hour=8, minute=0,
                      id='check_passwords', replace_existing=True)
    scheduler.add_job(check_certificates, 'cron', hour=8, minute=15,
                      id='check_certificates', replace_existing=True)
    scheduler.add_job(check_backups, 'cron', hour=8, minute=30,
                      id='check_backups', replace_existing=True)
    scheduler.add_job(check_tests, 'cron', hour=8, minute=45,
                      id='check_tests', replace_existing=True)
    scheduler.add_job(check_reviews, 'cron', hour=8, minute=50,
                      id='check_reviews', replace_existing=True)
    scheduler.add_job(check_updates, 'cron', hour=8, minute=55,
                      id='check_updates', replace_existing=True)

    scheduler.start()
