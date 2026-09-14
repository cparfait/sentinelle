"""Export PDF par entité (preuve d'audit pour une fiche individuelle)."""
import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

_BLUE = colors.HexColor('#3056a0')
_LIGHT = colors.HexColor('#f5f6f8')
_STATUS_COLOR = {
    'danger': colors.HexColor('#dc2626'),
    'warning': colors.HexColor('#d97706'),
    'info': colors.HexColor('#2563eb'),
    'success': colors.HexColor('#16a34a'),
}
_STATUS_LABEL = {'danger': 'Critique', 'warning': 'Attention', 'info': 'À surveiller', 'success': 'OK'}


def _base_styles():
    s = getSampleStyleSheet()
    return (
        ParagraphStyle('h1', parent=s['Title'], textColor=_BLUE, fontSize=18, spaceAfter=4),
        ParagraphStyle('h2', parent=s['Heading2'], textColor=colors.HexColor('#1e293b'), fontSize=12, spaceBefore=14),
        ParagraphStyle('small', parent=s['Normal'], textColor=colors.grey, fontSize=8),
        ParagraphStyle('body', parent=s['Normal'], fontSize=10),
    )


def _header_table_style():
    return TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), _LIGHT),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, _LIGHT]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ])


def _build(title, subtitle, rows, status=None, history=None):
    """Construit un PDF générique à partir d'une liste de (label, valeur)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    h1, h2, small, body = _base_styles()
    story = [
        Paragraph('Sentinelle — Fiche d\'audit', h1),
        Paragraph(f'Généré le {datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M")} UTC', small),
        Spacer(1, 0.3*cm),
    ]
    if status:
        sc = _STATUS_COLOR.get(status, colors.grey)
        sl = _STATUS_LABEL.get(status, status)
        story.append(Paragraph(f'<font color="#{sc.hexval()[2:]}">●</font> Statut : <b>{sl}</b>', body))
        story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(title, h2))
    if subtitle:
        story.append(Paragraph(subtitle, small))
    story.append(Spacer(1, 0.3*cm))

    if rows:
        tbl = Table([[Paragraph(str(k), body), Paragraph(str(v) if v is not None else '—', body)]
                     for k, v in rows], colWidths=[5*cm, None])
        tbl.setStyle(_header_table_style())
        story.append(tbl)

    if history:
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph('Historique récent', h2))
        hist_rows = [['Date', 'Action', 'Par', 'Commentaire']]
        for h in history[:20]:
            at = h.performed_at.strftime('%d/%m/%Y %H:%M') if h.performed_at else '—'
            hist_rows.append([at, h.action or '—', h.performed_by or '—', h.comment or '—'])
        htbl = Table(hist_rows, colWidths=[3.2*cm, 3*cm, 3*cm, None])
        htbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _BLUE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _LIGHT]),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(htbl)

    doc.build(story)
    return buf.getvalue()
