"""Export / import / modele CSV pour les principales entites.

CSV en UTF-8 avec BOM et separateur ';' (compatible Excel FR). L'import
detecte le separateur (';' ou ',') et accepte les dates JJ/MM/AAAA ou AAAA-MM-JJ.
"""
import io
import csv
from datetime import datetime, timedelta

from app import db
from app.models import (Account, Certificate, Domain, Backup, TestTask,
                        AccessReview, SystemUpdate, Equipment)


def _lookup_equipment(name):
    """Equipement actif portant ce nom (vue 360°), ou None si introuvable.
    Permet de relier en CSV par le nom plutot que par un id numerique."""
    return Equipment.query.filter_by(name=name, is_active=True).first()


def _parse_date(value):
    value = (value or '').strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_bool(value):
    v = (value or '').strip().lower()
    if v in ('oui', 'true', '1', 'yes', 'o', 'x'):
        return True
    if v in ('non', 'false', '0', 'no', 'n', ''):
        return False
    return None


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _parse(value, kind):
    value = (value or '').strip()
    if value == '':
        return None
    if kind == 'date':
        return _parse_date(value)
    if kind == 'bool':
        return _parse_bool(value)
    if kind == 'int':
        return _parse_int(value)
    if kind == 'equipment_ref':
        # Renvoie l'objet Equipment : affecte a la relation, il fixe equipment_id.
        return _lookup_equipment(value)
    return value


def _fmt(value, kind):
    if value is None:
        return ''
    if kind == 'date':
        return value.strftime('%Y-%m-%d')
    if kind == 'bool':
        return 'oui' if value else 'non'
    if kind == 'equipment_ref':
        return value.name  # value est l'objet Equipment lie
    return str(value)


def _account_post(obj):
    if obj.last_password_change and obj.rotation_days:
        obj.next_password_change = obj.last_password_change + timedelta(days=obj.rotation_days)


def _test_post(obj):
    if not obj.next_due and obj.last_performed and obj.frequency_days:
        obj.next_due = obj.last_performed + timedelta(days=obj.frequency_days)


def _review_post(obj):
    if not obj.next_review and obj.last_review and obj.frequency_days:
        obj.next_review = obj.last_review + timedelta(days=obj.frequency_days)


SPECS = {
    'accounts': {
        'model': Account, 'label': 'comptes', 'list_endpoint': 'accounts.list',
        'columns': [('service_name', 'str'), ('username', 'str'), ('url', 'str'),
                    ('description', 'str'), ('last_password_change', 'date'),
                    ('rotation_days', 'int'), ('priority', 'str')],
        'example': {'service_name': 'Active Directory', 'username': 'admin',
                    'url': 'https://ad.local', 'description': 'Compte admin',
                    'last_password_change': '2026-01-15', 'rotation_days': '90',
                    'priority': 'high'},
        'post': _account_post,
    },
    'certificates': {
        'model': Certificate, 'label': 'certificats', 'list_endpoint': 'certificates.list',
        'columns': [('service_name', 'str'), ('domain', 'str'), ('issuer', 'str'),
                    ('issued_at', 'date'), ('expiry_date', 'date'),
                    ('auto_renew', 'bool'), ('priority', 'str'), ('description', 'str'),
                    ('equipment', 'equipment_ref')],
        'example': {'service_name': 'Site web', 'domain': 'www.chatillon92.fr',
                    'issuer': "Let's Encrypt", 'issued_at': '2026-03-01',
                    'expiry_date': '2026-06-01', 'auto_renew': 'oui',
                    'priority': 'high', 'description': '', 'equipment': 'SRV-WEB-01'},
        'post': None,
    },
    'domains': {
        'model': Domain, 'label': 'domaines', 'list_endpoint': 'domains.list',
        'columns': [('name', 'str'), ('registrar', 'str'), ('expiry_date', 'date'),
                    ('auto_renew', 'bool'), ('priority', 'str'), ('description', 'str')],
        'example': {'name': 'chatillon92.fr', 'registrar': 'OVH',
                    'expiry_date': '2035-06-29', 'auto_renew': 'oui',
                    'priority': 'high', 'description': ''},
        'post': None,
    },
    'backups': {
        'model': Backup, 'label': 'backups', 'list_endpoint': 'backups.list',
        'columns': [('service_name', 'str'), ('backup_type', 'str'), ('location', 'str'),
                    ('frequency', 'str'), ('expected_time', 'str'),
                    ('priority', 'str'), ('description', 'str'),
                    ('equipment', 'equipment_ref')],
        'example': {'service_name': 'SQL Server Prod', 'backup_type': 'full',
                    'location': '\\\\nas\\backups\\sql', 'frequency': 'daily',
                    'expected_time': '02:00', 'priority': 'high', 'description': '',
                    'equipment': 'SRV-SQL-01'},
        'post': None,
    },
    'tests': {
        'model': TestTask, 'label': 'tests', 'list_endpoint': 'tests.list',
        'columns': [('name', 'str'), ('test_type', 'str'), ('description', 'str'),
                    ('last_performed', 'date'), ('next_due', 'date'),
                    ('frequency_days', 'int'), ('priority', 'str')],
        'example': {'name': 'Test de restauration', 'test_type': 'restoration',
                    'description': '', 'last_performed': '2026-01-10',
                    'next_due': '', 'frequency_days': '90', 'priority': 'high'},
        'post': _test_post,
    },
    'reviews': {
        'model': AccessReview, 'label': 'revues de droits', 'list_endpoint': 'reviews.list',
        'columns': [('application', 'str'), ('responsible', 'str'), ('scope', 'str'),
                    ('frequency_days', 'int'), ('last_review', 'date'),
                    ('next_review', 'date'), ('priority', 'str')],
        'example': {'application': 'SIRH', 'responsible': 'DRH', 'scope': 'Comptes RH',
                    'frequency_days': '365', 'last_review': '2026-01-15',
                    'next_review': '', 'priority': 'high'},
        'post': _review_post,
    },
    'updates': {
        'model': SystemUpdate, 'label': 'mises a jour', 'list_endpoint': 'updates.list',
        'columns': [('name', 'str'), ('system_type', 'str'), ('current_version', 'str'),
                    ('latest_version', 'str'), ('status', 'str'), ('last_update', 'date'),
                    ('updater_type', 'str'), ('updated_by', 'str'),
                    ('priority', 'str'), ('description', 'str'),
                    ('equipment', 'equipment_ref')],
        'example': {'name': 'Windows Server 2022', 'system_type': 'system',
                    'current_version': '21H2', 'latest_version': '21H2',
                    'status': 'up_to_date', 'last_update': '2026-05-01',
                    'updater_type': 'interne', 'updated_by': 'Jean Dupont',
                    'priority': 'high', 'description': '', 'equipment': 'SRV-AD-01'},
        'post': None,
    },
}


def is_valid(key):
    return key in SPECS


def _columns(key):
    return SPECS[key]['columns']


def export_csv(key):
    spec = SPECS[key]
    out = io.StringIO()
    out.write('﻿')  # BOM pour Excel
    writer = csv.writer(out, delimiter=';')
    cols = [c for c, _ in spec['columns']]
    writer.writerow(cols)
    for row in spec['model'].query.filter_by(is_active=True).all():
        writer.writerow([_fmt(getattr(row, c), k) for c, k in spec['columns']])
    return out.getvalue()


def template_csv(key):
    spec = SPECS[key]
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out, delimiter=';')
    cols = [c for c, _ in spec['columns']]
    writer.writerow(cols)
    writer.writerow([spec['example'].get(c, '') for c in cols])
    return out.getvalue()


def import_csv(key, raw_bytes):
    """Importe des enregistrements. Retourne (nb_crees, [erreurs])."""
    spec = SPECS[key]
    text = raw_bytes.decode('utf-8-sig', errors='replace')
    first_line = text.splitlines()[0] if text.strip() else ''
    delimiter = ';' if first_line.count(';') >= first_line.count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    key_col = spec['columns'][0][0]
    created = 0
    errors = []
    for line_no, row in enumerate(reader, start=2):
        # tolere les en-tetes avec espaces / casse
        norm = {(k or '').strip().lower(): v for k, v in row.items()}
        key_val = (norm.get(key_col.lower()) or '').strip()
        if not key_val:
            continue
        try:
            obj = spec['model']()
            for col, kind in spec['columns']:
                val = _parse(norm.get(col.lower()), kind)
                if val is not None:
                    setattr(obj, col, val)
            if spec['post']:
                spec['post'](obj)
            db.session.add(obj)
            created += 1
        except Exception as e:
            errors.append(f"Ligne {line_no} : {e}")
    if created:
        db.session.commit()
    return created, errors
