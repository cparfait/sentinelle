from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from app import db
from app.models import Account, Certificate, Backup, BackupCheck, TestTask
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


def start_scheduler(app):
    """Demarre le scheduler avec l'app reelle (sans la recreer dans les jobs)."""
    global _app
    _app = app

    if scheduler.running:
        return

    scheduler.add_job(refresh_certificates_tls, 'cron', hour=7, minute=0,
                      id='refresh_certificates_tls', replace_existing=True)
    scheduler.add_job(send_daily_digest, 'cron', hour=7, minute=30,
                      id='send_daily_digest', replace_existing=True)
    scheduler.add_job(check_passwords, 'cron', hour=8, minute=0,
                      id='check_passwords', replace_existing=True)
    scheduler.add_job(check_certificates, 'cron', hour=8, minute=15,
                      id='check_certificates', replace_existing=True)
    scheduler.add_job(check_backups, 'cron', hour=8, minute=30,
                      id='check_backups', replace_existing=True)
    scheduler.add_job(check_tests, 'cron', hour=8, minute=45,
                      id='check_tests', replace_existing=True)

    scheduler.start()
