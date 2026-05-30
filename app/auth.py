import os
import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from app.email_service import send_email, get_o365_auth_url, complete_o365_auth, is_o365_connected, get_o365_user_email, clear_o365_token
from app.audit import record as audit_record
from werkzeug.security import generate_password_hash

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        from datetime import datetime, timezone, timedelta
        from app.models import LoginThrottle
        username = request.form.get('username', '')
        password = request.form.get('password')
        now = datetime.now(timezone.utc)
        max_attempts = current_app.config.get('LOGIN_MAX_ATTEMPTS', 5)
        lockout_min = current_app.config.get('LOGIN_LOCKOUT_MINUTES', 15)

        throttle = LoginThrottle.query.filter_by(username=username).first()
        if throttle and throttle.locked_until and throttle.locked_until.replace(tzinfo=timezone.utc) > now:
            mins = int((throttle.locked_until.replace(tzinfo=timezone.utc) - now).total_seconds() // 60) + 1
            flash(f'Trop de tentatives. Reessayez dans {mins} minute(s).', 'danger')
            return render_template('auth/login.html')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if throttle:
                db.session.delete(throttle)
                db.session.commit()
            login_user(user)
            session.permanent = True  # applique PERMANENT_SESSION_LIFETIME (inactivite)
            audit_record('connexion', category='securite')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))

        # echec : incremente le compteur
        if not throttle:
            throttle = LoginThrottle(username=username, failed_count=0)
            db.session.add(throttle)
        throttle.failed_count = (throttle.failed_count or 0) + 1
        if throttle.failed_count >= max_attempts:
            throttle.locked_until = now + timedelta(minutes=lockout_min)
            throttle.failed_count = 0
            db.session.commit()
            audit_record('compte bloque', detail=f'identifiant: {username}', category='securite')
            flash(f'Trop de tentatives. Compte bloque {lockout_min} minute(s).', 'danger')
        else:
            db.session.commit()
            audit_record('echec connexion', detail=f'identifiant: {username}', category='securite')
            restantes = max_attempts - throttle.failed_count
            flash(f'Identifiants incorrects ({restantes} tentative(s) restante(s)).', 'danger')
    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    audit_record('deconnexion', category='securite')
    logout_user()
    return redirect(url_for('auth.login'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old = request.form.get('old_password')
            new = request.form.get('new_password')
            confirm = request.form.get('confirm_password')
            if not current_user.check_password(old):
                flash('Mot de passe actuel incorrect', 'danger')
            elif new != confirm:
                flash('Les mots de passe ne correspondent pas', 'danger')
            elif len(new) < current_app.config.get('PASSWORD_MIN_LENGTH', 8):
                _ml = current_app.config.get('PASSWORD_MIN_LENGTH', 8)
                flash(f'Le mot de passe doit contenir au moins {_ml} caracteres', 'danger')
            else:
                current_user.set_password(new)
                db.session.commit()
                audit_record('changement mot de passe', category='securite')
                flash('Mot de passe modifie avec succes', 'success')
        return redirect(url_for('auth.profile'))
    return render_template('auth/profile.html')


def _update_env_file(updates):
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    keys_written = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if '=' in stripped and not stripped.startswith('#'):
            key = stripped.split('=', 1)[0].strip()
            if key in updates:
                val = updates[key]
                lines[i] = f"{key}={val}\n"
                keys_written.add(key)
    for key, val in updates.items():
        if key not in keys_written:
            lines.append(f"{key}={val}\n")
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


@bp.route('/preferences', methods=['GET', 'POST'])
@login_required
def preferences():
    if not current_user.is_admin:
        flash('Acces reserve aux administrateurs', 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'set_mail_method':
            method = request.form.get('mail_method', 'smtp')
            _update_env_file({'MAIL_METHOD': method})
            current_app.config['MAIL_METHOD'] = method
            audit_record('config messagerie', detail=f'methode={method}', category='preferences')
            flash(f'Methode de messagerie changee en {method.upper()}', 'success')

        elif action == 'save_o365':
            client_id = request.form.get('o365_client_id', '').strip()
            client_secret = request.form.get('o365_client_secret', '').strip()
            tenant_id = request.form.get('o365_tenant_id', '').strip()
            sender_email = request.form.get('o365_sender_email', '').strip()
            redirect_uri = request.form.get('o365_redirect_uri', '').strip()
            updates = {
                'MAIL_METHOD': 'o365',
                'O365_CLIENT_ID': client_id,
                'O365_CLIENT_SECRET': client_secret,
                'O365_TENANT_ID': tenant_id,
                'O365_SENDER_EMAIL': sender_email,
                'O365_REDIRECT_URI': redirect_uri,
            }
            _update_env_file(updates)
            current_app.config['MAIL_METHOD'] = 'o365'
            current_app.config['O365_CLIENT_ID'] = client_id
            current_app.config['O365_CLIENT_SECRET'] = client_secret
            current_app.config['O365_TENANT_ID'] = tenant_id
            current_app.config['O365_SENDER_EMAIL'] = sender_email
            current_app.config['O365_REDIRECT_URI'] = redirect_uri
            audit_record('config messagerie', detail='Office 365', category='preferences')
            flash('Configuration Office 365 enregistree', 'success')

        elif action == 'disconnect_o365':
            clear_o365_token()
            flash('Compte Office 365 deconnecte', 'success')

        elif action == 'save_smtp':
            server = request.form.get('smtp_server', '').strip()
            port = request.form.get('smtp_port', '587').strip() or '587'
            username = request.form.get('smtp_username', '').strip()
            password = request.form.get('smtp_password', '').strip()
            # Adresse expeditrice, decouplee de l'identifiant : indispensable
            # pour le Direct Send (envoi sans authentification).
            sender = request.form.get('smtp_sender', '').strip() or username
            updates = {
                'MAIL_METHOD': 'smtp',
                'MAIL_SERVER': server,
                'MAIL_PORT': port,
                'MAIL_USERNAME': username,
                'MAIL_DEFAULT_SENDER': sender,
            }
            if password:
                updates['MAIL_PASSWORD'] = password
            _update_env_file(updates)
            current_app.config['MAIL_METHOD'] = 'smtp'
            current_app.config['MAIL_SERVER'] = server
            current_app.config['MAIL_PORT'] = int(port)
            current_app.config['MAIL_USERNAME'] = username
            current_app.config['MAIL_DEFAULT_SENDER'] = sender
            if password:
                current_app.config['MAIL_PASSWORD'] = password
            audit_record('config messagerie', detail=f'SMTP {server}', category='preferences')
            flash('Configuration SMTP enregistree', 'success')

        elif action == 'save_recipients':
            raw = request.form.get('alert_recipients', '')
            # accepte virgules, points-virgules, espaces et retours a la ligne
            parts = [p.strip() for p in re.split(r'[,;\s]+', raw) if p.strip()]
            recipients = list(dict.fromkeys(parts))  # dedoublonne en gardant l'ordre
            _update_env_file({'ALERT_RECIPIENTS': ','.join(recipients)})
            current_app.config['ALERT_RECIPIENTS'] = recipients
            audit_record('destinataires alertes', detail=f'{len(recipients)} adresse(s)', category='preferences')
            flash(f'{len(recipients)} destinataire(s) enregistre(s)', 'success')

        elif action == 'test_email':
            test_email_addr = request.form.get('test_email', '').strip()
            if not test_email_addr:
                test_email_addr = current_user.email
            try:
                send_email(
                    subject="Test de messagerie Sentinelle",
                    recipients=[test_email_addr],
                    body="Ceci est un email de test depuis Sentinelle. Si vous recevez cet email, la configuration de messagerie est correcte.",
                    html_body="<h2>Test de messagerie Sentinelle</h2><p>Ceci est un email de test depuis <strong>Sentinelle</strong>.</p><p>Si vous recevez cet email, la configuration de messagerie est <span style='color:green'>correcte</span>.</p><hr><small>Envoye automatiquement</small>"
                )
                flash(f'Email de test envoye avec succes a {test_email_addr}', 'success')
            except Exception as e:
                flash(f'Erreur envoi email: {str(e)}', 'danger')

        elif action == 'backup_db':
            from app.db_backup import backup_database
            try:
                path = backup_database(current_app)
                audit_record('sauvegarde base', detail=os.path.basename(path), category='base')
                flash(f"Base sauvegardee : {os.path.basename(path)}", 'success')
            except Exception as e:
                flash(f"Erreur sauvegarde base : {e}", 'danger')

        elif action == 'delete_db_backup':
            from app.db_backup import delete_backup
            try:
                _name = request.form.get('name', '')
                delete_backup(current_app, _name)
                audit_record('suppression sauvegarde base', detail=_name, category='base')
                flash('Sauvegarde supprimee', 'success')
            except Exception as e:
                flash(f"Suppression impossible : {e}", 'danger')

        elif action == 'save_thresholds':
            def _parse3(prefix, default):
                out = []
                for i, k in enumerate(('danger', 'warning', 'info')):
                    try:
                        out.append(max(0, int(request.form.get(f'{prefix}_{k}', default[i]))))
                    except (TypeError, ValueError):
                        out.append(default[i])
                return out
            groups = {
                'THRESHOLD_EXPIRY': _parse3('expiry', (7, 15, 30)),
                'THRESHOLD_DOMAIN': _parse3('domain', (30, 60, 90)),
                'THRESHOLD_TASK': _parse3('task', (7, 15, 30)),
            }
            _update_env_file({k: ','.join(str(x) for x in v) for k, v in groups.items()})
            for k, v in groups.items():
                current_app.config[k] = tuple(v)
            audit_record('config seuils alertes', category='preferences')
            flash('Seuils d\'alerte enregistres', 'success')

        elif action == 'send_digest':
            from app.digest import build_daily_digest
            addr = request.form.get('test_email', '').strip() or current_user.email
            subject, text_body, html_body, _ = build_daily_digest(
                current_app.config.get('APP_BASE_URL', ''))
            try:
                send_email(subject, [addr], text_body, html_body=html_body)
                flash(f'Recapitulatif envoye a {addr}', 'success')
            except Exception as e:
                flash(f'Erreur envoi recap: {str(e)}', 'danger')

        return redirect(url_for('auth.preferences'))

    mail_method = current_app.config.get('MAIL_METHOD', 'smtp')
    o365_connected = is_o365_connected()
    o365_user_email = get_o365_user_email()

    # On lit la config vivante (current_app.config), pas os.getenv : l'env du
    # processus n'est charge qu'au demarrage et n'est pas mis a jour lors d'un
    # enregistrement, ce qui ferait "disparaitre" les valeurs saisies.
    o365_config = {
        'client_id': current_app.config.get('O365_CLIENT_ID', ''),
        'client_secret': current_app.config.get('O365_CLIENT_SECRET', ''),
        'tenant_id': current_app.config.get('O365_TENANT_ID', ''),
        'sender_email': current_app.config.get('O365_SENDER_EMAIL', ''),
        'redirect_uri': current_app.config.get('O365_REDIRECT_URI', 'http://127.0.0.1:5000/auth/o365/callback'),
    }

    smtp_config = {
        'server': current_app.config.get('MAIL_SERVER', ''),
        'port': current_app.config.get('MAIL_PORT', '587'),
        'username': current_app.config.get('MAIL_USERNAME', ''),
        'sender': current_app.config.get('MAIL_DEFAULT_SENDER', ''),
    }

    alert_recipients = ', '.join(current_app.config.get('ALERT_RECIPIENTS', []) or [])

    from app.db_backup import list_backups
    db_backups = list_backups(current_app)

    thresholds = {
        'expiry': current_app.config.get('THRESHOLD_EXPIRY', (7, 15, 30)),
        'domain': current_app.config.get('THRESHOLD_DOMAIN', (30, 60, 90)),
        'task': current_app.config.get('THRESHOLD_TASK', (7, 15, 30)),
    }

    o365_app_configured = all([o365_config['client_id'], o365_config['client_secret'],
                               o365_config['tenant_id']])

    if mail_method == 'o365':
        mail_configured = o365_connected and o365_app_configured
    else:
        # Configure si un serveur + une adresse expeditrice (auth ou Direct Send)
        mail_configured = bool(smtp_config['server']
                               and (smtp_config['sender'] or smtp_config['username']))

    return render_template('auth/preferences.html', mail_method=mail_method,
                           mail_configured=mail_configured, o365_config=o365_config,
                           smtp_config=smtp_config, o365_connected=o365_connected,
                           o365_user_email=o365_user_email,
                           o365_app_configured=o365_app_configured,
                           alert_recipients=alert_recipients,
                           db_backups=db_backups, thresholds=thresholds)


@bp.route('/auth/o365/callback')
@login_required
def o365_callback():
    if not current_user.is_admin:
        flash('Acces reserve aux administrateurs', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        user_email = complete_o365_auth(dict(request.args))
        flash(f'Compte Office 365 connecte avec succes ({user_email})', 'success')
    except Exception as e:
        flash(f'Erreur connexion Office 365: {str(e)}', 'danger')

    return redirect(url_for('auth.preferences'))


@bp.route('/auth/o365/connect')
@login_required
def o365_connect():
    if not current_user.is_admin:
        flash('Acces reserve aux administrateurs', 'danger')
        return redirect(url_for('dashboard.index'))

    try:
        auth_url = get_o365_auth_url()
        if auth_url:
            return redirect(auth_url)
        flash('Configuration O365 incomplete. Renseignez Client ID, Tenant ID et Client Secret.', 'danger')
    except Exception as e:
        flash(f'Erreur OAuth2: {str(e)}', 'danger')
    return redirect(url_for('auth.preferences'))
