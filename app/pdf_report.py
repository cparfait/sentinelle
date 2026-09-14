"""Bilan PDF de la météo DSI (pour comité de pilotage)."""
import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from app.models import (Account, Certificate, Domain, Backup, TestTask,
                        AccessReview, SystemUpdate)

_CATS = [
    ('accounts', 'Comptes', Account, lambda o: o.status(), lambda o: f'{o.service_name} ({o.username})'),
    ('certificates', 'Certificats', Certificate, lambda o: o.status(), lambda o: f'{o.service_name} - {o.domain}'),
    ('domains', 'Domaines', Domain, lambda o: o.status(), lambda o: o.name),
    ('backups', 'Backups', Backup, lambda o: o.computed_status(), lambda o: o.service_name),
    ('tests', 'Tests', TestTask, lambda o: o.computed_status(), lambda o: o.name),
    ('reviews', 'Revue de droits', AccessReview, lambda o: o.computed_status(), lambda o: o.application),
    ('updates', 'Mises à jour', SystemUpdate, lambda o: o.status_color(), lambda o: o.name),
]
_INDIGO = colors.HexColor('#4f46e5')
_STATUS_COLOR = {'danger': colors.HexColor('#ef4444'), 'warning': colors.HexColor('#f59e0b'),
                 'info': colors.HexColor('#3b82f6'), 'success': colors.HexColor('#10b981')}


def build_pdf(user):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=_INDIGO, fontSize=20)
    small = ParagraphStyle('small', parent=styles['Normal'], textColor=colors.grey, fontSize=9)
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], textColor=colors.HexColor('#1e293b'))

    story = [Paragraph('Sentinelle — Bilan de supervision DSI', h1),
             Paragraph('Généré le ' + datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC'), small),
             Spacer(1, 0.6 * cm)]

    table = [['Catégorie', 'Total', 'Critique', 'Attention', 'Proche', 'OK']]
    totals = {'total': 0, 'danger': 0, 'warning': 0, 'info': 0, 'success': 0}
    urgent = []
    for cat, label, model, statusf, namef in _CATS:
        if not user.can_view(cat):
            continue
        items = model.query.filter_by(is_active=True).all()
        cnt = {'danger': 0, 'warning': 0, 'info': 0, 'success': 0}
        for o in items:
            s = statusf(o)
            if s in cnt:
                cnt[s] += 1
            if s in ('danger', 'warning'):
                urgent.append((label, namef(o), s))
        table.append([label, str(len(items)), str(cnt['danger']),
                      str(cnt['warning']), str(cnt['info']), str(cnt['success'])])
        totals['total'] += len(items)
        for k in cnt:
            totals[k] += cnt[k]

    conformity = round(100 * totals['success'] / totals['total']) if totals['total'] else 100
    story.append(Paragraph(f'Conformité globale : <b>{conformity}%</b> '
                           f'({totals["success"]} OK / {totals["total"]} éléments suivis)', h2))
    story.append(Spacer(1, 0.3 * cm))

    t = Table(table, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), _INDIGO),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))

    story.append(Paragraph('Éléments à traiter', h2))
    if urgent:
        urgent.sort(key=lambda x: 0 if x[2] == 'danger' else 1)
        rows = [['Statut', 'Catégorie', 'Élément']]
        for label, name, s in urgent:
            rows.append(['Critique' if s == 'danger' else 'Attention', label, name])
        ut = Table(rows, hAlign='LEFT', colWidths=[2.5 * cm, 3.5 * cm, 10 * cm])
        st = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
              ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
              ('FONTSIZE', (0, 0), (-1, -1), 9),
              ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
              ('PADDING', (0, 0), (-1, -1), 4)]
        for i, (_, _, s) in enumerate(urgent, start=1):
            st.append(('TEXTCOLOR', (0, i), (0, i), _STATUS_COLOR[s]))
        ut.setStyle(TableStyle(st))
        story.append(ut)
    else:
        story.append(Paragraph('Aucun élément critique ou à surveiller. ✓', styles['Normal']))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                      leftMargin=1.5 * cm, rightMargin=1.5 * cm).build(story)
    return buf.getvalue()


def send_report(recipients=None):
    """Genere le bilan PDF et l'envoie par mail (job planifie ou bouton
    « Envoyer maintenant » des Preferences). Retourne les destinataires."""
    from flask import current_app
    from app.models import User
    from app.email_service import send_email

    recipients = [r.strip() for r in (recipients
                  or current_app.config.get('REPORT_RECIPIENTS')
                  or current_app.config.get('ALERT_RECIPIENTS') or [])
                  if r and r.strip()]
    if not recipients:
        raise Exception('Aucun destinataire configure pour le bilan PDF.')

    # Vision complete : le rapport planifie est genere avec les droits admin.
    admin = next((u for u in User.query.all() if u.is_admin), None)
    if admin is None:
        raise Exception('Aucun compte administrateur trouve.')

    pdf = build_pdf(admin)
    stamp = datetime.now(timezone.utc).strftime('%d/%m/%Y')
    send_email(
        subject=f'Bilan de supervision DSI du {stamp}',
        recipients=recipients,
        body=("Veuillez trouver ci-joint le bilan de supervision Sentinelle "
              f"genere le {stamp}.\n\nCe message est envoye automatiquement."),
        attachments=[(f"sentinelle-bilan-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf",
                      pdf, 'application/pdf')],
    )
    return recipients
