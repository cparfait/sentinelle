import os
import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from app.email_service import send_email, get_o365_auth_url, complete_o365_auth, is_o365_connected, get_o365_user_email, clear_o365_token
from app.audit import record as audit_record
from app.decorators import require_admin

bp = Blueprint('auth', __name__)


def _safe_next(value):
    """Ne garde le parametre `next` que s'il s'agit d'un chemin interne
    (evite la redirection ouverte vers un site externe apres connexion)."""
    if value and value.startswith('/') and not value.startswith('//'):
        return value
    return None


@bp.route('/login', methods=['GET', 'POST'])
def login():
    # Deja connecte : la page de login n'a pas de sens (et rendait une page vide)
    if current_user.is_authenticated:
        resp = redirect(url_for('dashboard.index'))
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    if request.method == 'POST':
        from datetime import datetime, timezone, timedelta
        from app.models import LoginThrottle
        username = request.form.get('username', '')
        password = request.form.get('password')
        # Adresse source : le blocage est par (identifiant, IP) afin qu'un tiers
        # ne puisse pas verrouiller le compte d'un collegue depuis ailleurs.
        ip = (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
              or request.remote_addr or '')
        now = datetime.now(timezone.utc)
        max_attempts = current_app.config.get('LOGIN_MAX_ATTEMPTS', 5)
        lockout_min = current_app.config.get('LOGIN_LOCKOUT_MINUTES', 15)

        throttle = LoginThrottle.query.filter_by(username=username, ip=ip).first()
        if throttle and throttle.locked_until and throttle.locked_until.replace(tzinfo=timezone.utc) > now:
            mins = int((throttle.locked_until.replace(tzinfo=timezone.utc) - now).total_seconds() // 60) + 1
            flash(f'Trop de tentatives. Reessayez dans {mins} minute(s).', 'danger')
            return render_template('auth/login.html')

        # Authentification hybride : mot de passe local d'abord, puis LDAP/AD.
        user = User.query.filter_by(username=username).first()
        authed = bool(user and user.check_password(password))
        ldap_used = False
        if not authed:
            from app.ldap_auth import ldap_authenticate
            info = ldap_authenticate(username, password)
            if info is not None:
                authed = True
                ldap_used = True
                if user is None:
                    user = _provision_ldap_user(username, info)

        if authed and user is not None:
            if throttle:
                db.session.delete(throttle)
                db.session.commit()
            if user.totp_secret:
                # 2FA active : on differe la connexion jusqu'a verification du code
                session['pending_2fa_uid'] = user.id
                session['pending_2fa_ldap'] = ldap_used
                session['pending_2fa_next'] = _safe_next(request.args.get('next'))
                return redirect(url_for('auth.two_factor'))
            login_user(user)
            session.permanent = True  # applique PERMANENT_SESSION_LIFETIME (inactivite)
            audit_record('connexion' + (' (LDAP)' if ldap_used else ''), category='securite')
            next_page = _safe_next(request.args.get('next'))
            return redirect(next_page or url_for('dashboard.index'))

        # echec : incremente le compteur
        if not throttle:
            throttle = LoginThrottle(username=username, ip=ip, failed_count=0)
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


@bp.route('/2fa', methods=['GET', 'POST'])
def two_factor():
    uid = session.get('pending_2fa_uid')
    if not uid:
        return redirect(url_for('auth.login'))
    user = db.session.get(User, uid)
    if not user or not user.totp_secret:
        session.pop('pending_2fa_uid', None)
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        import pyotp
        code = (request.form.get('code') or '').strip().replace(' ', '')
        if pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            ldap_used = session.pop('pending_2fa_ldap', False)
            nxt = _safe_next(session.pop('pending_2fa_next', None))
            session.pop('pending_2fa_uid', None)
            login_user(user)
            session.permanent = True
            audit_record('connexion (2FA)' + (' LDAP' if ldap_used else ''), category='securite')
            return redirect(nxt or url_for('dashboard.index'))
        audit_record('echec 2FA', detail=user.username, category='securite')
        flash('Code de vérification invalide.', 'danger')
    return render_template('auth/two_factor.html')


def _totp_qr_svg(secret, username):
    """QR code TOTP renvoye comme <img> data-URI : robuste a l'insertion HTML
    (le SVG inline cassait l'affichage a cause du prologue XML / namespaces)."""
    import io
    import base64
    import pyotp
    import qrcode
    import qrcode.image.svg
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name='Sentinelle')
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return (f'<img src="data:image/svg+xml;base64,{b64}" alt="QR code 2FA" '
            f'style="width:100%;height:auto;display:block;">')


def _provision_ldap_user(username, info):
    """Cree un compte local pour un utilisateur AD valide (mot de passe local
    inutilisable ; il s'authentifiera toujours via LDAP)."""
    import secrets
    role = current_app.config.get('LDAP_DEFAULT_ROLE', 'viewer')
    domain = current_app.config.get('LDAP_DOMAIN') or 'ldap.local'
    email = (info or {}).get('email') or f'{username}@{domain}'
    if User.query.filter_by(email=email).first():
        email = f'{username}@ldap.local'
    u = User(username=username, email=email, role=role, auth_source='ldap')
    u.set_password(secrets.token_urlsafe(24))
    db.session.add(u)
    db.session.commit()
    audit_record('creation utilisateur (LDAP)', detail=f'{username} (role {role})',
                 category='utilisateurs')
    return u


@bp.route('/logout')
@login_required
def logout():
    audit_record('deconnexion', category='securite')
    logout_user()
    return redirect(url_for('auth.login'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    import pyotp
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

        elif action == 'init_2fa':
            secret = pyotp.random_base32()
            session['setup_2fa'] = secret
            return render_template('auth/profile.html', setup_secret=secret,
                                   qr_svg=_totp_qr_svg(secret, current_user.username))

        elif action == 'confirm_2fa':
            secret = session.get('setup_2fa')
            code = (request.form.get('code') or '').strip().replace(' ', '')
            if secret and pyotp.TOTP(secret).verify(code, valid_window=1):
                current_user.totp_secret = secret
                db.session.commit()
                session.pop('setup_2fa', None)
                audit_record('activation 2FA', category='securite')
                flash('Double authentification activée.', 'success')
                return redirect(url_for('auth.profile'))
            flash('Code invalide, réessayez.', 'danger')
            if secret:
                return render_template('auth/profile.html', setup_secret=secret,
                                       qr_svg=_totp_qr_svg(secret, current_user.username))
            return redirect(url_for('auth.profile'))

        elif action == 'disable_2fa':
            if current_user.check_password(request.form.get('password', '')):
                current_user.totp_secret = None
                db.session.commit()
                audit_record('desactivation 2FA', category='securite')
                flash('Double authentification désactivée.', 'success')
            else:
                flash('Mot de passe incorrect.', 'danger')
            return redirect(url_for('auth.profile'))

        return redirect(url_for('auth.profile'))
    return render_template('auth/profile.html')


def _persist_config(updates):
    """Persiste les reglages applicatifs en base (table AppConfig, secrets
    chiffres). Remplace l'ancienne ecriture dans .env."""
    from app import config_store
    config_store.save(updates)


@bp.route('/preferences', methods=['GET', 'POST'])
@login_required
@require_admin
def preferences():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'set_mail_method':
            method = request.form.get('mail_method', 'smtp')
            _persist_config({'MAIL_METHOD': method})
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
            _persist_config(updates)
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
            _persist_config(updates)
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
            from app.config_store import ALERT_CATEGORIES

            def _parse_emails(raw):
                # accepte virgules, points-virgules, espaces et retours a la ligne
                parts = [p.strip() for p in re.split(r'[,;\s]+', raw or '') if p.strip()]
                return list(dict.fromkeys(parts))  # dedoublonne en gardant l'ordre

            recipients = _parse_emails(request.form.get('alert_recipients', ''))
            updates = {'ALERT_RECIPIENTS': ','.join(recipients)}
            current_app.config['ALERT_RECIPIENTS'] = recipients
            # Listes par categorie (vide = repli sur la liste globale)
            for cat in ALERT_CATEGORIES:
                cat_recipients = _parse_emails(request.form.get(f'alert_recipients_{cat}', ''))
                key = f'ALERT_RECIPIENTS_{cat.upper()}'
                updates[key] = ','.join(cat_recipients)
                current_app.config[key] = cat_recipients
            _persist_config(updates)
            audit_record('destinataires alertes', detail=f'{len(recipients)} adresse(s) globales', category='preferences')
            flash('Destinataires enregistrés', 'success')

        elif action == 'save_report':
            schedule = request.form.get('report_schedule', 'off')
            if schedule not in ('off', 'weekly', 'monthly'):
                schedule = 'off'
            parts = [p.strip() for p in re.split(r'[,;\s]+', request.form.get('report_recipients', '')) if p.strip()]
            recipients = list(dict.fromkeys(parts))
            _persist_config({'REPORT_SCHEDULE': schedule,
                             'REPORT_RECIPIENTS': ','.join(recipients)})
            current_app.config['REPORT_SCHEDULE'] = schedule
            current_app.config['REPORT_RECIPIENTS'] = recipients
            audit_record('planification bilan PDF', detail=schedule, category='preferences')
            flash('Planification du bilan PDF enregistrée', 'success')

        elif action == 'send_report_now':
            from app.pdf_report import send_report
            try:
                sent_to = send_report()
                audit_record('envoi bilan PDF', detail=f'{len(sent_to)} destinataire(s)', category='preferences')
                flash(f'Bilan PDF envoyé à {", ".join(sent_to)}', 'success')
            except Exception as e:
                flash(f'Erreur envoi bilan : {e}', 'danger')

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

        elif action == 'save_webhooks':
            mapping = {
                'TEAMS_WEBHOOK_URL': request.form.get('teams_webhook', '').strip(),
                'SLACK_WEBHOOK_URL': request.form.get('slack_webhook', '').strip(),
                'DISCORD_WEBHOOK_URL': request.form.get('discord_webhook', '').strip(),
            }
            _persist_config(mapping)
            current_app.config.update(mapping)
            audit_record('config notifications', category='preferences')
            flash('Notifications enregistrees', 'success')

        elif action in ('test_teams', 'test_slack', 'test_discord'):
            from app import notify
            fn = {'test_teams': notify.send_teams, 'test_slack': notify.send_slack,
                  'test_discord': notify.send_discord}[action]
            ok = fn('Test de notification', 'Notification de test depuis Sentinelle.',
                    status='info', url=current_app.config.get('APP_BASE_URL'))
            canal = action.split('_')[1].capitalize()
            flash(f'Notification {canal} envoyee.' if ok else f"Echec {canal} (verifier l'URL du webhook).",
                  'success' if ok else 'danger')

        elif action == 'save_ldap':
            enabled = request.form.get('ldap_enabled') == 'on'
            use_ssl = request.form.get('ldap_ssl') == 'on'
            validate_cert = request.form.get('ldap_validate_cert') == 'on'
            port = request.form.get('ldap_port', '389').strip() or '389'
            # Certificat CA : chemin saisi, ou fichier importe (prioritaire).
            ca_path = request.form.get('ldap_ca_cert', '').strip()
            ca_file = request.files.get('ldap_ca_cert_file')
            if ca_file and ca_file.filename:
                # NB : pas de `import os` local ici — il rendrait `os` locale a
                # toute la fonction et casserait les actions plus haut (UnboundLocalError).
                os.makedirs(current_app.instance_path, exist_ok=True)
                dest = os.path.join(current_app.instance_path, 'ldap_ca.pem')
                ca_file.save(dest)
                ca_path = dest
                flash(f'Certificat CA importé ({ca_file.filename}).', 'info')
            updates = {
                'LDAP_ENABLED': 'true' if enabled else 'false',
                'LDAP_SERVER': request.form.get('ldap_server', '').strip(),
                'LDAP_PORT': port,
                'LDAP_USE_SSL': 'true' if use_ssl else 'false',
                'LDAP_VALIDATE_CERT': 'true' if validate_cert else 'false',
                'LDAP_CA_CERT': ca_path,
                'LDAP_DOMAIN': request.form.get('ldap_domain', '').strip(),
                'LDAP_BASE_DN': request.form.get('ldap_base_dn', '').strip(),
                'LDAP_REQUIRED_GROUP': request.form.get('ldap_required_group', '').strip(),
                'LDAP_DEFAULT_ROLE': request.form.get('ldap_default_role', 'viewer'),
                'LDAP_BIND_USER': request.form.get('ldap_bind_user', '').strip(),
            }
            bind_pw = request.form.get('ldap_bind_password', '')
            if bind_pw:
                updates['LDAP_BIND_PASSWORD'] = bind_pw
            _persist_config(updates)
            current_app.config.update(
                LDAP_ENABLED=enabled, LDAP_SERVER=updates['LDAP_SERVER'],
                LDAP_PORT=int(port), LDAP_USE_SSL=use_ssl,
                LDAP_VALIDATE_CERT=validate_cert, LDAP_CA_CERT=updates['LDAP_CA_CERT'],
                LDAP_DOMAIN=updates['LDAP_DOMAIN'], LDAP_BASE_DN=updates['LDAP_BASE_DN'],
                LDAP_REQUIRED_GROUP=updates['LDAP_REQUIRED_GROUP'],
                LDAP_DEFAULT_ROLE=updates['LDAP_DEFAULT_ROLE'],
                LDAP_BIND_USER=updates['LDAP_BIND_USER'])
            if bind_pw:
                current_app.config['LDAP_BIND_PASSWORD'] = bind_pw
            audit_record('config LDAP', detail=f'actif={enabled}', category='preferences')
            flash('Configuration LDAP enregistree', 'success')

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
                'THRESHOLD_CONTRACT': _parse3('contract', (60, 90, 180)),
            }
            _persist_config({k: ','.join(str(x) for x in v) for k, v in groups.items()})
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

        elif action == 'add_asset':
            from app.models import Asset
            from app.app_settings import get_asset_type_values
            name = request.form.get('asset_name', '').strip()
            atype = request.form.get('asset_type', 'application')
            if atype not in get_asset_type_values():
                atype = 'application'
            if not name:
                flash('Le nom est obligatoire.', 'danger')
            else:
                db.session.add(Asset(name=name, asset_type=atype,
                                     description=request.form.get('asset_description', '').strip() or None))
                db.session.commit()
                audit_record('ajout catalogue', detail=f'{name} ({atype})', category='preferences')
                flash('Élément ajouté au catalogue', 'success')

        elif action == 'edit_asset':
            from app.models import Asset
            a = Asset.query.get(request.form.get('asset_id', type=int))
            if a:
                name = request.form.get('asset_name', '').strip()
                atype = request.form.get('asset_type', a.asset_type)
                from app.app_settings import get_asset_type_values
                if atype not in get_asset_type_values():
                    atype = a.asset_type
                if not name:
                    flash('Le nom est obligatoire.', 'danger')
                else:
                    a.name = name
                    a.asset_type = atype
                    a.description = request.form.get('asset_description', '').strip() or None
                    db.session.commit()
                    audit_record('modification catalogue', detail=f'{name} ({atype})', category='preferences')
                    flash('Élément du catalogue modifié', 'success')

        elif action == 'delete_asset':
            from app.models import Asset
            a = Asset.query.get(request.form.get('asset_id', type=int))
            if a:
                name = a.name
                db.session.delete(a)
                db.session.commit()
                audit_record('suppression catalogue', detail=name, category='preferences')
                flash('Élément retiré du catalogue', 'success')

        elif action == 'save_conformity':
            from app.app_settings import set_conformity_categories
            set_conformity_categories(request.form.getlist('conformity'))
            audit_record('config conformite', detail='Conformite globale', category='preferences')
            flash('Catégories de la conformité globale enregistrées', 'success')

        elif action == 'add_asset_type':
            from app.app_settings import add_asset_type
            label = request.form.get('type_label', '').strip()
            if add_asset_type(label):
                audit_record('ajout type catalogue', detail=label, category='preferences')
                flash(f'Type « {label} » ajouté', 'success')
            else:
                flash('Type vide ou déjà existant.', 'warning')

        elif action == 'delete_asset_type':
            from app.app_settings import remove_asset_type
            label = request.form.get('type_label', '').strip()
            if remove_asset_type(label):
                audit_record('suppression type catalogue', detail=label, category='preferences')
                flash(f'Type « {label} » retiré', 'success')

        elif action == 'test_ldap':
            from app.ldap_auth import test_ldap_connection
            ok, msg = test_ldap_connection(current_app)
            flash(msg, 'success' if ok else 'danger')

        elif action == 'add_webhook':
            from app.models import Webhook, WEBHOOK_CHANNELS, CATEGORY_LABELS
            channel = request.form.get('wh_channel', '')
            url = request.form.get('wh_url', '').strip()
            category = request.form.get('wh_category', 'all')
            if channel not in WEBHOOK_CHANNELS:
                flash('Canal invalide.', 'danger')
            elif not url:
                flash("L'URL du webhook est obligatoire.", 'danger')
            else:
                if category != 'all' and category not in CATEGORY_LABELS:
                    category = 'all'
                db.session.add(Webhook(category=category, channel=channel, url=url,
                                       label=request.form.get('wh_label', '').strip() or None))
                db.session.commit()
                audit_record('ajout webhook', detail=f'{channel} / {category}', category='preferences')
                flash('Webhook ajouté', 'success')

        elif action == 'delete_webhook':
            from app.models import Webhook
            w = Webhook.query.get(request.form.get('wh_id', type=int))
            if w:
                db.session.delete(w)
                db.session.commit()
                audit_record('suppression webhook', detail=f'{w.channel} / {w.category}', category='preferences')
                flash('Webhook supprimé', 'success')

        elif action == 'test_webhook':
            from app.models import Webhook
            from app.notify import send_to
            w = Webhook.query.get(request.form.get('wh_id', type=int))
            if w:
                ok = send_to(w.channel, w.url, 'Test de notification',
                             'Ceci est un message de test depuis Sentinelle.', status='info',
                             url=current_app.config.get('APP_BASE_URL'))
                flash('Test envoyé.' if ok else "Échec de l'envoi du test.",
                      'success' if ok else 'danger')

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
    from app.config_store import ALERT_CATEGORIES, ALERT_CATEGORY_LABELS
    alert_recipients_by_cat = {
        cat: ', '.join(current_app.config.get(f'ALERT_RECIPIENTS_{cat.upper()}') or [])
        for cat in ALERT_CATEGORIES}
    webhooks = {
        'teams': current_app.config.get('TEAMS_WEBHOOK_URL', ''),
        'slack': current_app.config.get('SLACK_WEBHOOK_URL', ''),
        'discord': current_app.config.get('DISCORD_WEBHOOK_URL', ''),
    }

    from app.db_backup import list_backups
    db_backups = list_backups(current_app)

    from app.models import Asset, ASSET_TYPE_LABELS, CONFORMITY_CATEGORIES, CATEGORY_LABELS
    assets = Asset.query.order_by(Asset.asset_type, Asset.name).all()

    from app.app_settings import (get_conformity_categories, get_asset_types,
                                  _BUILTIN_ASSET_TYPES)
    conformity_included = set(get_conformity_categories())
    asset_types = get_asset_types()
    builtin_type_values = {v for v, _ in _BUILTIN_ASSET_TYPES}

    from app.models import Webhook, WEBHOOK_CHANNELS
    category_webhooks = Webhook.query.order_by(Webhook.category, Webhook.channel).all()

    thresholds = {
        'expiry': current_app.config.get('THRESHOLD_EXPIRY', (7, 15, 30)),
        'domain': current_app.config.get('THRESHOLD_DOMAIN', (30, 60, 90)),
        'task': current_app.config.get('THRESHOLD_TASK', (7, 15, 30)),
        'contract': current_app.config.get('THRESHOLD_CONTRACT', (60, 90, 180)),
    }
    ldap_config = {
        'enabled': current_app.config.get('LDAP_ENABLED', False),
        'server': current_app.config.get('LDAP_SERVER', ''),
        'port': current_app.config.get('LDAP_PORT', 389),
        'ssl': current_app.config.get('LDAP_USE_SSL', False),
        'validate_cert': current_app.config.get('LDAP_VALIDATE_CERT', True),
        'ca_cert': current_app.config.get('LDAP_CA_CERT', ''),
        'domain': current_app.config.get('LDAP_DOMAIN', ''),
        'base_dn': current_app.config.get('LDAP_BASE_DN', ''),
        'required_group': current_app.config.get('LDAP_REQUIRED_GROUP', ''),
        'default_role': current_app.config.get('LDAP_DEFAULT_ROLE', 'viewer'),
        'bind_user': current_app.config.get('LDAP_BIND_USER', ''),
        'bind_set': bool(current_app.config.get('LDAP_BIND_PASSWORD')),
    }

    o365_app_configured = all([o365_config['client_id'], o365_config['client_secret'],
                               o365_config['tenant_id']])

    if mail_method == 'o365':
        mail_configured = o365_connected and o365_app_configured
    else:
        # Configure si un serveur + une adresse expeditrice (auth ou Direct Send)
        mail_configured = bool(smtp_config['server']
                               and (smtp_config['sender'] or smtp_config['username']))

    # Indicateur « Configuré » par bloc : vrai si l'admin y a renseigne qqch.
    from app.models import Setting
    _thr_defaults = {'expiry': (7, 15, 30), 'domain': (30, 60, 90), 'task': (7, 15, 30)}
    configured = {
        'mail': mail_configured,
        'recipients': bool(alert_recipients.strip()),
        'notify': bool(webhooks['teams'] or webhooks['slack'] or webhooks['discord']
                       or category_webhooks),
        'assets': bool(assets),
        'ldap': bool(ldap_config['enabled']),
        'conformity': db.session.get(Setting, 'conformity_categories') is not None,
        'thresholds': any(tuple(thresholds[k]) != _thr_defaults[k] for k in _thr_defaults),
        'db': bool(db_backups),
    }

    return render_template('auth/preferences.html', mail_method=mail_method,
                           configured=configured,
                           mail_configured=mail_configured, o365_config=o365_config,
                           smtp_config=smtp_config, o365_connected=o365_connected,
                           o365_user_email=o365_user_email,
                           o365_app_configured=o365_app_configured,
                           alert_recipients=alert_recipients,
                           alert_recipients_by_cat=alert_recipients_by_cat,
                           alert_category_labels=ALERT_CATEGORY_LABELS,
                           report_schedule=current_app.config.get('REPORT_SCHEDULE', 'off'),
                           report_recipients=', '.join(current_app.config.get('REPORT_RECIPIENTS') or []),
                           db_backups=db_backups, thresholds=thresholds,
                           ldap_config=ldap_config, webhooks=webhooks,
                           assets=assets, asset_type_labels=ASSET_TYPE_LABELS,
                           asset_types=asset_types, builtin_type_values=builtin_type_values,
                           conformity_categories=CONFORMITY_CATEGORIES,
                           conformity_labels=CATEGORY_LABELS,
                           conformity_included=conformity_included,
                           category_webhooks=category_webhooks,
                           webhook_channels=WEBHOOK_CHANNELS,
                           gestion_categories=CONFORMITY_CATEGORIES)


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
