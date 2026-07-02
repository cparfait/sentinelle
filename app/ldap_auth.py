"""Authentification LDAP / Active Directory (en complément du compte local).

L'authentification locale et LDAP cohabitent : on tente d'abord le mot de passe
local, puis (si activé) un bind LDAP. Un utilisateur AD valide est provisionné
automatiquement en base avec le rôle par défaut configuré.
"""
from flask import current_app


def ldap_enabled():
    return bool(current_app.config.get('LDAP_ENABLED') and current_app.config.get('LDAP_SERVER'))


def build_server(cfg):
    """Construit le Server ldap3 avec gestion LDAPS (TLS) : port 636 par defaut,
    validation du certificat configurable, CA optionnelle."""
    import ssl
    from ldap3 import Server, Tls, ALL
    raw = (cfg.get('LDAP_SERVER') or '').strip()
    # Schema optionnel : on accepte un simple FQDN/IP. Si l'utilisateur a saisi
    # ldap:// ou ldaps://, on le detecte puis on le retire (ldap3 attend l'hote).
    low = raw.lower()
    scheme_ssl = None
    if low.startswith('ldaps://'):
        scheme_ssl, raw = True, raw[8:]
    elif low.startswith('ldap://'):
        scheme_ssl, raw = False, raw[7:]
    host = raw.rstrip('/').strip()
    use_ssl = bool(cfg.get('LDAP_USE_SSL')) or scheme_ssl is True
    port = int(cfg.get('LDAP_PORT') or 0) or (636 if use_ssl else 389)
    if use_ssl and port == 389:  # port en clair laisse par defaut -> LDAPS standard
        port = 636
    tls = None
    if use_ssl:
        if cfg.get('LDAP_VALIDATE_CERT', True):
            validate = ssl.CERT_REQUIRED
        else:
            validate = ssl.CERT_NONE
        ca = cfg.get('LDAP_CA_CERT') or None
        tls = Tls(validate=validate, ca_certs_file=ca)
    return Server(host, port=port, use_ssl=use_ssl, tls=tls, get_info=ALL, connect_timeout=8)


def test_ldap_connection(app=None):
    """Teste la connexion LDAP (et le bind du compte de service si renseigne).
    Retourne (ok: bool, message: str) pour affichage direct a l'admin."""
    cfg = (app or current_app).config
    if not cfg.get('LDAP_ENABLED'):
        return False, "LDAP désactivé : activez-le puis enregistrez avant de tester."
    if not cfg.get('LDAP_SERVER'):
        return False, "Aucun serveur LDAP configuré."
    try:
        from ldap3 import Connection
    except ImportError:
        return False, "Module ldap3 non installé."
    bind_user = cfg.get('LDAP_BIND_USER')
    bind_pw = cfg.get('LDAP_BIND_PASSWORD')
    try:
        server = build_server(cfg)
        # Protocole reellement utilise (build_server force 636 quand SSL est actif).
        if server.ssl:
            validated = 'certificat validé' if cfg.get('LDAP_VALIDATE_CERT', True) \
                else 'certificat non validé'
            proto = f"LDAPS (TLS, port {server.port}, {validated})"
        else:
            proto = f"LDAP non chiffré (port {server.port})"
        if bind_user and bind_pw:
            conn = Connection(server, user=bind_user, password=bind_pw, auto_bind=True)
            base = cfg.get('LDAP_BASE_DN')
            if base:
                conn.search(base, '(objectClass=*)', search_scope='BASE')
            conn.unbind()
            return True, (f"Connexion et authentification réussies via {proto} "
                          f"(compte de service : {bind_user}).")
        conn = Connection(server, auto_bind=True)
        conn.unbind()
        return True, f"Connexion au serveur LDAP réussie via {proto} (aucun compte de service configuré)."
    except Exception as e:
        return False, f"Échec de connexion LDAP : {e}"


def _esc(v):
    """Echappe une valeur pour un filtre LDAP (RFC 4515)."""
    out = (v or '')
    for ch, rep in (('\\', '\\5c'), ('(', '\\28'), (')', '\\29'), ('*', '\\2a'), ('\x00', '\\00')):
        out = out.replace(ch, rep)
    return out


def _user_in_group(conn, base, username, group):
    """Vrai si l'utilisateur appartient au groupe AD (groupes imbriques inclus).
    `group` peut etre un DN (CN=...,DC=...) ou un simple nom (cn/sAMAccountName)."""
    group = (group or '').strip()
    if not group:
        return True
    group_dn = group
    try:
        if '=' not in group:   # nom simple -> resoudre le DN du groupe
            conn.search(base, '(&(objectClass=group)(|(cn=%s)(sAMAccountName=%s)))'
                        % (_esc(group), _esc(group)), attributes=['cn'])
            if not conn.entries:
                return False
            group_dn = conn.entries[0].entry_dn
        # Appartenance recursive (matching rule AD LDAP_MATCHING_RULE_IN_CHAIN)
        conn.search(base, '(&(sAMAccountName=%s)(memberOf:1.2.840.113556.1.4.1941:=%s))'
                    % (_esc(username), group_dn), attributes=['cn'])
        if conn.entries:
            return True
        # Repli : appartenance directe via memberOf
        conn.search(base, '(sAMAccountName=%s)' % _esc(username), attributes=['memberOf'])
        if conn.entries and 'memberOf' in conn.entries[0]:
            mof = [str(x).lower() for x in conn.entries[0].memberOf]
            return group_dn.lower() in mof
    except Exception as e:
        current_app.logger.info('Verif groupe LDAP echouee pour %s : %s', username, e)
        return False
    return False


def ldap_authenticate(username, password):
    """Tente un bind LDAP. Retourne un dict d'infos (succès) ou None (échec/désactivé)."""
    if not ldap_enabled() or not username or not password:
        return None
    try:
        from ldap3 import Connection
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
        server = build_server(cfg)
        conn = Connection(server, user=bind_user, password=password, auto_bind=True)
    except Exception as e:
        current_app.logger.info('Echec bind LDAP pour %s : %s', username, e)
        return None

    base = cfg.get('LDAP_BASE_DN')
    required_group = (cfg.get('LDAP_REQUIRED_GROUP') or '').strip()

    # Restriction d'acces a un groupe AD (fortement conseille) : si configure,
    # seul un membre peut se connecter. Echec ferme si non verifiable.
    if required_group:
        if not base:
            current_app.logger.warning(
                'LDAP_REQUIRED_GROUP defini mais LDAP_BASE_DN vide : acces refuse a %s', username)
            try:
                conn.unbind()
            except Exception:
                pass
            return None
        if not _user_in_group(conn, base, username, required_group):
            current_app.logger.info(
                'Acces LDAP refuse pour %s : pas membre du groupe « %s »', username, required_group)
            try:
                conn.unbind()
            except Exception:
                pass
            return None

    info = {'email': None, 'display_name': None}
    if base:
        try:
            conn.search(base, f'(sAMAccountName={_esc(username)})',
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
        from ldap3 import Connection
        server = build_server(cfg)
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
            conn.search(base, f'(sAMAccountName={_esc(uname)})',
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
