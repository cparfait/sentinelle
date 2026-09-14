import os
import json
import smtplib
from email.message import EmailMessage
import msal
import requests as http_requests
from flask import current_app, session


def _token_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'o365_token.json')


def _load_token():
    path = _token_path()
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        raw = f.read()
    if not raw:
        return None
    # Nouveau format : chiffre (Fernet). Repli sur l'ancien format JSON en clair
    # pour migrer sans intervention (le prochain _save_token reecrira chiffre).
    try:
        from app.config_store import _fernet
        raw = _fernet().decrypt(raw)
    except Exception:
        pass
    try:
        return json.loads(raw)
    except Exception:
        return None


def _save_token(access_token, refresh_token, user_email=''):
    """Stocke le token O365 chiffre (refresh_token = donnee sensible). La cle
    derive de SECRET_KEY (meme mecanisme que les secrets de config)."""
    payload = json.dumps({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user_email': user_email,
    }).encode('utf-8')
    try:
        from app.config_store import _fernet
        data = _fernet().encrypt(payload)
    except Exception:
        current_app.logger.warning('Chiffrement du token O365 indisponible : stockage en clair.')
        data = payload
    with open(_token_path(), 'wb') as f:
        f.write(data)


def clear_o365_token():
    path = _token_path()
    if os.path.exists(path):
        os.remove(path)


def is_o365_connected():
    token_data = _load_token()
    return bool(token_data and token_data.get('refresh_token'))


def get_o365_user_email():
    token_data = _load_token()
    if token_data:
        return token_data.get('user_email', '')
    return ''


def get_o365_auth_url():
    client_id = current_app.config.get('O365_CLIENT_ID', '')
    tenant_id = current_app.config.get('O365_TENANT_ID', '')
    redirect_uri = current_app.config.get('O365_REDIRECT_URI', '')

    if not client_id or not tenant_id:
        return None

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    msal_app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=current_app.config.get('O365_CLIENT_SECRET', ''),
    )

    scopes = ["Mail.Send", "User.Read"]
    flow = msal_app.initiate_auth_code_flow(
        scopes,
        redirect_uri=redirect_uri,
    )
    session['o365_flow'] = flow
    return flow.get('auth_uri')


def complete_o365_auth(query_params):
    client_id = current_app.config.get('O365_CLIENT_ID', '')
    tenant_id = current_app.config.get('O365_TENANT_ID', '')

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    msal_app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=current_app.config.get('O365_CLIENT_SECRET', ''),
    )

    flow = session.pop('o365_flow', None)
    if not flow:
        raise Exception("Session OAuth2 expiree. Reessayez.")

    result = msal_app.acquire_token_by_auth_code_flow(flow, query_params)

    if 'error' in result:
        raise Exception(f"Erreur OAuth2: {result.get('error_description', result['error'])}")

    access_token = result.get('access_token')
    refresh_token = result.get('refresh_token', '')

    user_resp = http_requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    user_email = ''
    if user_resp.status_code == 200:
        user_data = user_resp.json()
        user_email = user_data.get('mail') or user_data.get('userPrincipalName', '')
    else:
        current_app.logger.warning(
            'O365 : recuperation de l\'email emetteur echouee (HTTP %s).',
            user_resp.status_code)

    _save_token(access_token, refresh_token, user_email)

    return user_email


def get_o365_access_token():
    token_data = _load_token()
    if not token_data:
        return None

    if token_data.get('refresh_token'):
        client_id = current_app.config.get('O365_CLIENT_ID', '')
        tenant_id = current_app.config.get('O365_TENANT_ID', '')
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        msal_app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=current_app.config.get('O365_CLIENT_SECRET', ''),
        )
        result = msal_app.acquire_token_by_refresh_token(
            token_data['refresh_token'],
            scopes=["Mail.Send"],
        )
        if 'access_token' in result:
            new_refresh = result.get('refresh_token', token_data['refresh_token'])
            _save_token(result['access_token'], new_refresh, token_data.get('user_email', ''))
            return result['access_token']
        else:
            clear_o365_token()
            return None

    return None


def send_email(subject, recipients, body, html_body=None, attachments=None):
    """attachments : liste de tuples (nom_fichier, contenu_bytes, mimetype)."""
    method = current_app.config.get('MAIL_METHOD', 'smtp')
    if method == 'o365':
        return _send_via_graph(subject, recipients, body, html_body, attachments)
    return _send_via_smtp(subject, recipients, body, html_body, attachments)


_STATUS_COLORS = {
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'info': '#3b82f6',
    'success': '#10b981',
}


def render_alert_email(title, body, status='danger', url=None):
    """Habille un message d'alerte en HTML (charte Sentinelle, barre de statut).
    Si `url` est fourni, ajoute un bouton "Voir la fiche"."""
    from html import escape
    bar = _STATUS_COLORS.get(status, '#4f46e5')
    body_html = escape(body).replace('\n', '<br>')
    button = ''
    if url:
        button = (
            f'<div style="margin-top:18px;"><a href="{escape(url)}" '
            'style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;'
            'padding:9px 18px;border-radius:6px;font-size:14px;font-weight:600;">'
            'Voir la fiche &rarr;</a></div>'
        )
    return (
        '<!DOCTYPE html><html lang="fr"><body style="margin:0;background:#f1f5f9;'
        'font-family:Segoe UI,Arial,sans-serif;color:#334155;">'
        '<div style="max-width:600px;margin:24px auto;background:#fff;border-radius:10px;'
        'overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);">'
        '<div style="background:linear-gradient(135deg,#6366f1,#3b82f6);padding:16px 24px;'
        'color:#fff;font-size:18px;font-weight:700;letter-spacing:.5px;">&#128737; Sentinelle</div>'
        f'<div style="height:4px;background:{bar};"></div>'
        '<div style="padding:24px;">'
        f'<h2 style="margin:0 0 12px;font-size:18px;color:#1e293b;">{escape(title)}</h2>'
        f'<div style="font-size:14px;line-height:1.6;">{body_html}</div>'
        f'{button}'
        '</div>'
        '<div style="padding:14px 24px;background:#f8fafc;color:#94a3b8;font-size:12px;'
        'border-top:1px solid #e2e8f0;">Message automatique — Sentinelle, supervision DSI.</div>'
        '</div></body></html>'
    )


def _send_via_smtp(subject, recipients, body, html_body=None, attachments=None):
    """Envoi SMTP, compatible aussi bien avec un serveur authentifie qu'avec
    le "Direct Send" Microsoft 365 (relais par IP, sans identifiants).

    - Si MAIL_USERNAME et MAIL_PASSWORD sont fournis -> authentification.
    - Sinon -> envoi sans authentification (Direct Send / relais interne).
    On lit la config vivante (current_app.config) a chaque envoi pour prendre
    en compte les reglages saisis via Preferences sans redemarrage.
    """
    server = current_app.config.get('MAIL_SERVER')
    port = int(current_app.config.get('MAIL_PORT') or 25)
    use_tls = current_app.config.get('MAIL_USE_TLS', True)
    username = (current_app.config.get('MAIL_USERNAME') or '').strip()
    password = current_app.config.get('MAIL_PASSWORD') or ''
    sender = ((current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
              or username)

    if not server:
        raise Exception("Aucun serveur SMTP configure dans Preferences.")
    if not sender:
        raise Exception("Aucune adresse expeditrice configuree dans Preferences.")

    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        raise Exception("Aucun destinataire.")

    # EmailMessage gere proprement l'UTF-8 du sujet et du corps.
    msg = EmailMessage()
    msg['Subject'] = f"[Sentinelle] {subject}"
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype='html')
    for name, data, mimetype in (attachments or []):
        maintype, _, subtype = (mimetype or 'application/octet-stream').partition('/')
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

    # local_hostname force en ASCII : evite un EHLO avec un nom de machine
    # accentue qui ferait planter smtplib ('ascii' codec can't encode...).
    with smtplib.SMTP(server, port, local_hostname='sentinelle', timeout=30) as smtp:
        smtp.ehlo()
        if use_tls and smtp.has_extn('starttls'):
            smtp.starttls()
            smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True


def _send_via_graph(subject, recipients, body, html_body=None, attachments=None):
    access_token = get_o365_access_token()
    if not access_token:
        raise Exception("Token O365 expire. Reconnectez-vous via Preferences.")

    sender = current_app.config.get('O365_SENDER_EMAIL', '')
    if not sender:
        raise Exception("Email emetteur non configure.")

    email_data = {
        "message": {
            "subject": f"[Sentinelle] {subject}",
            "body": {
                "contentType": "HTML" if html_body else "Text",
                "content": html_body or body
            },
            "toRecipients": [
                {"emailAddress": {"address": r.strip()}}
                for r in recipients if r.strip()
            ]
        }
    }
    if attachments:
        import base64
        email_data["message"]["attachments"] = [
            {"@odata.type": "#microsoft.graph.fileAttachment",
             "name": name,
             "contentType": mimetype or 'application/octet-stream',
             "contentBytes": base64.b64encode(data).decode('ascii')}
            for name, data, mimetype in attachments
        ]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    endpoint = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    response = http_requests.post(endpoint, headers=headers, json=email_data, timeout=30)

    if response.status_code not in (200, 202):
        raise Exception(f"Envoi echoue (HTTP {response.status_code}): {response.text}")

    return True
