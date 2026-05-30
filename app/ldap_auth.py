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
