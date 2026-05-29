"""Construit le recapitulatif quotidien de la meteo DSI (un seul email)."""
from datetime import datetime, timezone
from html import escape

from app.models import Account, Certificate, Backup, TestTask
from app.snooze import is_snoozed

_COLORS = {'danger': '#ef4444', 'warning': '#f59e0b', 'info': '#3b82f6',
           'success': '#10b981'}
_LABELS = {'danger': 'Critique', 'warning': 'Attention', 'info': 'A surveiller',
           'success': 'OK'}


def _collect():
    """Retourne la liste des domaines avec compteurs et elements non-verts."""
    today = datetime.now(timezone.utc).date()
    domains = []

    def days_txt(d, kind):
        if d is None:
            return 'date non renseignee'
        n = (d - today).days
        if kind == 'expire':
            return f'expire dans {n} j' if n >= 0 else f'expire depuis {abs(n)} j'
        return f'dans {n} j' if n >= 0 else f'en retard de {abs(n)} j'

    # Comptes
    accounts = Account.query.filter_by(is_active=True).all()
    items = []
    for a in accounts:
        if is_snoozed('account', a.id):
            continue
        s = a.status()
        if s in ('danger', 'warning'):
            items.append({'name': f'{a.service_name} ({a.username})',
                          'detail': 'Mot de passe ' + days_txt(a.next_password_change, 'expire'),
                          'status': s, 'path': f'/accounts/{a.id}'})
    domains.append({'key': 'Comptes', 'total': len(accounts), 'items': items})

    # Certificats
    certs = Certificate.query.filter_by(is_active=True).all()
    items = []
    for c in certs:
        if is_snoozed('certificate', c.id):
            continue
        s = c.status()
        if s in ('danger', 'warning'):
            items.append({'name': f'{c.service_name} - {c.domain}',
                          'detail': 'Certificat ' + days_txt(c.expiry_date, 'expire'),
                          'status': s, 'path': f'/certificates/{c.id}'})
    domains.append({'key': 'Certificats', 'total': len(certs), 'items': items})

    # Backups
    backups = Backup.query.filter_by(is_active=True).all()
    items = []
    for b in backups:
        if is_snoozed('backup', b.id):
            continue
        s = b.computed_status()
        if s in ('danger', 'warning'):
            tc = b.today_check()
            detail = 'Non verifie aujourd\'hui' if not tc else f'Check du jour : {tc.status}'
            items.append({'name': b.service_name, 'detail': detail,
                          'status': s, 'path': f'/backups/{b.id}'})
    domains.append({'key': 'Backups', 'total': len(backups), 'items': items})

    # Tests
    tests = TestTask.query.filter_by(is_active=True).all()
    items = []
    for t in tests:
        if is_snoozed('test', t.id):
            continue
        s = t.computed_status()
        if s in ('danger', 'warning'):
            items.append({'name': t.name,
                          'detail': 'Test ' + days_txt(t.next_due, 'due'),
                          'status': s, 'path': f'/tests/{t.id}'})
    domains.append({'key': 'Tests', 'total': len(tests), 'items': items})

    return domains


def build_daily_digest(base_url=''):
    """Retourne (subject, text_body, html_body, has_urgent)."""
    base = (base_url or '').rstrip('/')
    domains = _collect()
    today = datetime.now(timezone.utc).date().strftime('%d/%m/%Y')

    all_items = [it for d in domains for it in d['items']]
    n_danger = sum(1 for it in all_items if it['status'] == 'danger')
    n_warning = sum(1 for it in all_items if it['status'] == 'warning')
    has_urgent = bool(all_items)

    # --- Sujet ---
    if n_danger:
        subject = f"Meteo DSI du {today} - {n_danger} critique(s), {n_warning} a surveiller"
    elif n_warning:
        subject = f"Meteo DSI du {today} - {n_warning} a surveiller"
    else:
        subject = f"Meteo DSI du {today} - tout est au vert"

    # --- Texte brut ---
    lines = [f"Meteo DSI du {today}", ""]
    if not has_urgent:
        lines.append("Tout est au vert : aucun element critique ni a surveiller.")
    else:
        for d in domains:
            if d['items']:
                lines.append(f"== {d['key']} ==")
                for it in d['items']:
                    lines.append(f"  [{_LABELS[it['status']]}] {it['name']} - {it['detail']}")
                lines.append("")
    text_body = "\n".join(lines)

    # --- HTML ---
    pills = ''
    for d in domains:
        nd = sum(1 for it in d['items'] if it['status'] == 'danger')
        nw = sum(1 for it in d['items'] if it['status'] == 'warning')
        color = _COLORS['danger'] if nd else (_COLORS['warning'] if nw else _COLORS['success'])
        badge = f'{nd + nw} a traiter' if (nd or nw) else 'OK'
        pills += (
            f'<td style="padding:6px;"><div style="border:1px solid #e2e8f0;border-radius:8px;'
            f'padding:10px;text-align:center;"><div style="font-size:12px;color:#64748b;">{escape(d["key"])}</div>'
            f'<div style="font-size:13px;font-weight:700;color:{color};margin-top:4px;">{badge}</div>'
            f'<div style="font-size:11px;color:#94a3b8;">{d["total"]} suivis</div></div></td>'
        )

    blocks = ''
    if not has_urgent:
        blocks = ('<div style="padding:16px;background:#ecfdf5;border:1px solid #a7f3d0;'
                  'border-radius:8px;color:#065f46;">Tout est au vert : aucun element critique '
                  'ni a surveiller aujourd\'hui.</div>')
    else:
        for d in domains:
            if not d['items']:
                continue
            rows = ''
            for it in d['items']:
                link = f'{base}{it["path"]}' if base else None
                name_cell = (f'<a href="{escape(link)}" style="color:#4f46e5;text-decoration:none;">{escape(it["name"])}</a>'
                             if link else escape(it['name']))
                rows += (
                    f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;">'
                    f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                    f'background:{_COLORS[it["status"]]};margin-right:6px;"></span>{name_cell}</td>'
                    f'<td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#64748b;'
                    f'font-size:13px;">{escape(it["detail"])}</td></tr>'
                )
            blocks += (
                f'<h3 style="font-size:14px;color:#1e293b;margin:18px 0 6px;">{escape(d["key"])}</h3>'
                f'<table style="width:100%;border-collapse:collapse;font-size:14px;">{rows}</table>'
            )

    html_body = (
        '<!DOCTYPE html><html lang="fr"><body style="margin:0;background:#f1f5f9;'
        'font-family:Segoe UI,Arial,sans-serif;color:#334155;">'
        '<div style="max-width:640px;margin:24px auto;background:#fff;border-radius:10px;'
        'overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);">'
        '<div style="background:linear-gradient(135deg,#6366f1,#3b82f6);padding:16px 24px;'
        f'color:#fff;"><span style="font-size:18px;font-weight:700;">&#128737; Meteo DSI</span>'
        f'<span style="float:right;font-size:13px;opacity:.85;">{today}</span></div>'
        '<div style="padding:20px 24px;">'
        f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr>{pills}</tr></table>'
        f'<div style="margin-top:8px;">{blocks}</div>'
        '</div>'
        '<div style="padding:14px 24px;background:#f8fafc;color:#94a3b8;font-size:12px;'
        'border-top:1px solid #e2e8f0;">Recapitulatif automatique — Sentinelle, supervision DSI.</div>'
        '</div></body></html>'
    )

    return subject, text_body, html_body, has_urgent
