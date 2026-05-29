"""Lecture en direct des certificats TLS pour mettre a jour automatiquement
la date d'expiration (et l'emetteur) des fiches Certificat.

On se connecte au domaine en TLS, sans verifier la chaine (verify_mode=NONE)
afin de fonctionner aussi avec des certificats internes / auto-signes : le but
est de LIRE la date d'expiration reelle, pas de valider la confiance.
"""
import ssl
import socket
from urllib.parse import urlparse
from datetime import timezone

from cryptography import x509
from cryptography.x509.oid import NameOID


def parse_host_port(domain, default_port=443):
    """Extrait (host, port) d'une saisie souple : 'ex.fr', 'https://ex.fr/x',
    'ex.fr:8443'."""
    value = (domain or '').strip()
    if not value:
        raise ValueError("Domaine vide")
    if '://' in value:
        parsed = urlparse(value)
        host = parsed.hostname
        port = parsed.port or default_port
    else:
        # enleve un eventuel chemin
        value = value.split('/', 1)[0]
        if ':' in value:
            host, _, port_str = value.partition(':')
            port = int(port_str) if port_str.isdigit() else default_port
        else:
            host, port = value, default_port
    if not host:
        raise ValueError(f"Domaine invalide : {domain}")
    return host, port


def _issuer_common_name(cert):
    try:
        attrs = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) \
            or cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        if attrs:
            return attrs[0].value
    except Exception:
        pass
    return None


def fetch_cert_info(domain, port=None, timeout=10):
    """Retourne {'expiry_date': date, 'issuer': str|None} pour le certificat
    presente par le domaine. Leve une exception en cas d'echec (injoignable,
    pas de TLS, etc.)."""
    host, parsed_port = parse_host_port(domain)
    port = port or parsed_port

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)

    if not der:
        raise ValueError("Aucun certificat presente par le serveur")

    cert = x509.load_der_x509_certificate(der)
    expiry = cert.not_valid_after_utc.astimezone(timezone.utc).date()
    return {'expiry_date': expiry, 'issuer': _issuer_common_name(cert)}
