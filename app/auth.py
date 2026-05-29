import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from app.email_service import send_email, get_o365_auth_url, complete_o365_auth, is_o365_connected, get_o365_user_email, clear_o365_token
from werkzeug.security import generate_password_hash

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))
        flash('Identifiants incorrects', 'danger')
    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
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
            elif len(new) < 8:
                flash('Le mot de passe doit contenir au moins 8 caracteres', 'danger')
            else:
                current_user.set_password(new)
                db.session.commit()
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
            flash('Configuration Office 365 enregistree', 'success')

        elif action == 'disconnect_o365':
            clear_o365_token()
            flash('Compte Office 365 deconnecte', 'success')

        elif action == 'save_smtp':
            server = request.form.get('smtp_server', '').strip()
            port = request.form.get('smtp_port', '587').strip()
            username = request.form.get('smtp_username', '').strip()
            password = request.form.get('smtp_password', '').strip()
            updates = {
                'MAIL_METHOD': 'smtp',
                'MAIL_SERVER': server,
                'MAIL_PORT': port,
                'MAIL_USERNAME': username,
            }
            if password:
                updates['MAIL_PASSWORD'] = password
            # L'adresse expeditrice doit correspondre a la boite authentifiee,
            # sinon Microsoft 365 (et beaucoup d'autres) rejette l'envoi.
            if username:
                updates['MAIL_DEFAULT_SENDER'] = username
            _update_env_file(updates)
            current_app.config['MAIL_METHOD'] = 'smtp'
            current_app.config['MAIL_SERVER'] = server
            current_app.config['MAIL_PORT'] = int(port)
            current_app.config['MAIL_USERNAME'] = username
            if password:
                current_app.config['MAIL_PASSWORD'] = password
            if username:
                current_app.config['MAIL_DEFAULT_SENDER'] = username
            flash('Configuration SMTP enregistree', 'success')

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
    }

    o365_app_configured = all([o365_config['client_id'], o365_config['client_secret'],
                               o365_config['tenant_id']])

    if mail_method == 'o365':
        mail_configured = o365_connected and o365_app_configured
    else:
        mail_configured = all([smtp_config['server'], smtp_config['username']])

    return render_template('auth/preferences.html', mail_method=mail_method,
                           mail_configured=mail_configured, o365_config=o365_config,
                           smtp_config=smtp_config, o365_connected=o365_connected,
                           o365_user_email=o365_user_email,
                           o365_app_configured=o365_app_configured)


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
