"""Authentification LDAP / Active Directory (en complément du compte local).

L'authentification locale et LDAP cohabitent : on tente d'abord le mot de passe
local, puis (si activé) un bind LDAP. Un utilisateur AD valide est provisionné
automatiquement en base avec le rôle par défaut configuré.
"""
from flask import current_app


def ldap_enabled():
    return bool(current_app.config.get('LDAP_ENABLED') and current_app.config.get('LDAP_SERVER'))


def ldap_authenticate(username, password):
    """Tente un bind LDAP. Retourne un dict d'infos (succès) ou None (échec/désactivé)."""
    if not ldap_enabled() or not username or not password:
        return None
    try:
        from ldap3 import Server, Connection, ALL
    except ImportError:
        current_app.logger.error('ldap3 non installe')
        return None

    cfg = current_app.config
    domain = cfg.get('LDAP_DOMAIN', '')
    # Identifiant de bind : UPN (user@domaine) par defaut, sinon gabarit DN.
    template = cfg.get('LDAP_USER_DN_TEMPLATE', '')
    if template:
        bind_user = template.format(username=username)
    elif domain:
        bind_user = f'{username}@{domain}'
    else:
        bind_user = username

    try:
        server = Server(cfg['LDAP_SERVER'], port=int(cfg.get('LDAP_PORT', 389) or 389),
                        use_ssl=bool(cfg.get('LDAP_USE_SSL', False)), get_info=ALL,
                        connect_timeout=8)
        conn = Connection(server, user=bind_user, password=password, auto_bind=True)
    except Exception as e:
        current_app.logger.info('Echec bind LDAP pour %s : %s', username, e)
        return None

    info = {'email': None, 'display_name': None}
    base = cfg.get('LDAP_BASE_DN')
    if base:
        try:
            conn.search(base, f'(sAMAccountName={username})',
                        attributes=['mail', 'displayName'])
            if conn.entries:
                entry = conn.entries[0]
                if 'mail' in entry and entry.mail:
                    info['email'] = str(entry.mail)
                if 'displayName' in entry and entry.displayName:
                    info['display_name'] = str(entry.displayName)
        except Exception:
            pass
    try:
        conn.unbind()
    except Exception:
        pass
    return info


# FILETIME Windows -> date (100-ns depuis 1601-01-01 UTC)
_FILETIME_NEVER = (0, 9223372036854775807)


def _filetime_to_date(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value in _FILETIME_NEVER:
        return None  # mot de passe sans expiration
    from datetime import datetime, timedelta, timezone
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    return (epoch + timedelta(microseconds=value // 10)).date()


def sync_password_expirations():
    """Met a jour next_password_change des comptes dont le username correspond
    a un compte AD (sAMAccountName), d'apres msDS-UserPasswordExpiryTimeComputed.
    Necessite un compte de service (LDAP_BIND_USER/PASSWORD). Retourne (maj, erreurs)."""
    from flask import current_app
    from app import db
    from app.models import Account, AccountHistory
    cfg = current_app.config
    if not ldap_enabled() or not cfg.get('LDAP_BIND_USER') or not cfg.get('LDAP_BASE_DN'):
        return 0, ['LDAP/compte de service/Base DN non configures']
    try:
        from ldap3 import Server, Connection, ALL
        server = Server(cfg['LDAP_SERVER'], port=int(cfg.get('LDAP_PORT', 389) or 389),
                        use_ssl=bool(cfg.get('LDAP_USE_SSL', False)), get_info=ALL, connect_timeout=8)
        conn = Connection(server, user=cfg['LDAP_BIND_USER'],
                          password=cfg['LDAP_BIND_PASSWORD'], auto_bind=True)
    except Exception as e:
        return 0, [f'Connexion AD impossible : {e}']

    updated = 0
    errors = []
    base = cfg['LDAP_BASE_DN']
    for acc in Account.query.filter_by(is_active=True).all():
        uname = (acc.username or '').strip()
        if not uname:
            continue
        try:
            conn.search(base, f'(sAMAccountName={uname})',
                        attributes=['msDS-UserPasswordExpiryTimeComputed'])
            if not conn.entries:
                continue
            raw = conn.entries[0]['msDS-UserPasswordExpiryTimeComputed'].value
            expiry = _filetime_to_date(raw)
            if expiry and expiry != acc.next_password_change:
                acc.next_password_change = expiry
                db.session.add(AccountHistory(
                    account_id=acc.id, action='ad_sync',
                    comment=f'Expiration synchronisee depuis AD : {expiry.strftime("%d/%m/%Y")}',
                    performed_by='auto-ad'))
                updated += 1
        except Exception as e:
            errors.append(f'{uname}: {e}')
    if updated:
        db.session.commit()
    try:
        conn.unbind()
    except Exception:
        pass
    return updated, errors
