import os
import json
import msal
import requests as http_requests
from flask import current_app, session
from flask_mail import Message
from app import mail


def _token_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'o365_token.json')


def _load_token():
    path = _token_path()
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return None


def _save_token(access_token, refresh_token, user_email=''):
    path = _token_path()
    with open(path, 'w') as f:
        json.dump({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user_email': user_email,
        }, f)


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


def send_email(subject, recipients, body, html_body=None):
    method = current_app.config.get('MAIL_METHOD', 'smtp')
    if method == 'o365':
        return _send_via_graph(subject, recipients, body, html_body)
    return _send_via_smtp(subject, recipients, body, html_body)


def _send_via_smtp(subject, recipients, body, html_body=None):
    # A defaut d'expediteur configure, on utilise l'identifiant SMTP : c'est
    # la boite authentifiee, donc le seul "From" accepte par Microsoft 365.
    sender = (current_app.config.get('MAIL_DEFAULT_SENDER')
              or current_app.config.get('MAIL_USERNAME'))
    if not sender:
        raise Exception("Aucune adresse expeditrice configuree. "
                        "Renseignez l'utilisateur SMTP dans Preferences.")
    if not current_app.config.get('MAIL_SERVER'):
        raise Exception("Aucun serveur SMTP configure dans Preferences.")
    # Flask-Mail fige sa config a l'init_app : on la rafraichit a partir de la
    # config vivante pour prendre en compte les reglages saisis via Preferences
    # sans avoir a redemarrer l'application.
    mail.init_app(current_app)
    msg = Message(
        subject=f"[Sentinelle] {subject}",
        sender=sender,
        recipients=recipients,
        body=body,
        html=html_body
    )
    mail.send(msg)
    return True


def _send_via_graph(subject, recipients, body, html_body=None):
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

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    endpoint = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    response = http_requests.post(endpoint, headers=headers, json=email_data, timeout=30)

    if response.status_code not in (200, 202):
        raise Exception(f"Envoi echoue (HTTP {response.status_code}): {response.text}")

    return True
