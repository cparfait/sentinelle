"""Surveillance Certificate Transparency : detecte les certificats nouvellement
emis pour les domaines suivis et alerte la DSI.

Modele : au premier scan d'un domaine, on etablit une ligne de base silencieuse
(les certificats deja publies ne declenchent pas d'alerte). Ensuite, tout nouveau
certificat apparaissant dans les journaux CT declenche une alerte.
"""
from datetime import datetime, timezone

from flask import current_app

from app import db
from app.models import Domain, CtLogEntry, DomainHistory
from app.ct_checker import fetch_ct_certificates
from app.snooze import is_snoozed
from app.alerts import send_alert


def _persist(domain, cert, status):
    entry = CtLogEntry(
        domain_id=domain.id,
        crtsh_id=cert['crtsh_id'],
        serial_number=cert['serial_number'],
        common_name=cert['common_name'],
        name_value=cert['name_value'],
        issuer_name=cert['issuer_name'],
        not_before=cert['not_before'],
        not_after=cert['not_after'],
        entry_timestamp=cert['entry_timestamp'],
        status=status,
    )
    db.session.add(entry)
    return entry


def scan_domain(domain, performed_by='auto-ct', fetcher=None, do_alert=True):
    """Scanne crt.sh pour un domaine, enregistre les certificats et alerte sur
    les nouveaux. Commit inclus. Retourne {baseline: int, new: [CtLogEntry], error}."""
    fetcher = fetcher or fetch_ct_certificates
    try:
        certs = fetcher(domain.name)
    except Exception as e:
        db.session.add(DomainHistory(
            domain_id=domain.id, action='ct_scan_failed',
            comment=f"Scan CT impossible : {e}", performed_by=performed_by))
        db.session.commit()
        return {'baseline': 0, 'new': [], 'error': str(e)}

    known = {row.crtsh_id for row in domain.ct_entries}
    fresh = [c for c in certs if c['crtsh_id'] not in known]
    max_id = max((c['crtsh_id'] for c in certs), default=None)

    # Premier scan : ligne de base silencieuse, on n'alerte pas sur l'historique.
    if domain.ct_last_id is None:
        for c in fresh:
            _persist(domain, c, 'baseline')
        domain.ct_last_id = max_id
        db.session.add(DomainHistory(
            domain_id=domain.id, action='ct_baseline',
            comment=f"Ligne de base CT etablie : {len(fresh)} certificat(s) connu(s).",
            performed_by=performed_by))
        db.session.commit()
        return {'baseline': len(fresh), 'new': [], 'error': None}

    new_entries = [_persist(domain, c, 'new') for c in fresh]
    if max_id is not None:
        domain.ct_last_id = max(domain.ct_last_id or 0, max_id)
    if fresh:
        db.session.add(DomainHistory(
            domain_id=domain.id, action='ct_new_cert',
            comment=f"{len(fresh)} nouveau(x) certificat(s) detecte(s) dans les journaux CT.",
            performed_by=performed_by))
    db.session.commit()

    if do_alert and new_entries and not is_snoozed('domain', domain.id):
        _alert(domain, new_entries)
    return {'baseline': 0, 'new': new_entries, 'error': None}


def _alert(domain, entries):
    lines = []
    for e in entries[:20]:
        names = ', '.join(e.sans()[:5]) or e.common_name or '(sans nom)'
        nb = e.not_before.strftime('%d/%m/%Y') if e.not_before else '?'
        lines.append(f"- {names}\n    Emetteur : {e.issuer_name or '?'} | emis le {nb}")
    extra = f"\n(+ {len(entries) - 20} autre(s) certificat(s))" if len(entries) > 20 else ''
    body = (
        f"{len(entries)} nouveau(x) certificat(s) ont ete emis pour le domaine "
        f"{domain.name} (ou un sous-domaine) et publies dans les journaux de "
        f"Certificate Transparency.\n\n"
        f"Verifiez leur legitimite (nouveau service, prestataire, ou emission "
        f"frauduleuse) :\n\n"
        + '\n'.join(lines) + extra + '\n'
    )
    send_alert(f"Certificats CT inconnus - {domain.name}", body,
               'ct', domain.id, domain.name, status='warning')


def run_ct_scan():
    """Scanne tous les domaines actifs dont la surveillance CT est activee."""
    if not current_app.config.get('CT_MONITORING', True):
        return
    for domain in Domain.query.filter_by(is_active=True).all():
        if not getattr(domain, 'ct_enabled', True):
            continue
        try:
            scan_domain(domain)
        except Exception:
            db.session.rollback()
