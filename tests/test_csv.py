"""Import/export CSV : la colonne « equipment » relie par le nom (vue 360°)."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import Equipment, Certificate
from app import csv_io


def test_export_certificat_ecrit_le_nom_equipement(app):
    e = Equipment(name='SRV-WEB-01')
    db.session.add(e)
    db.session.commit()
    db.session.add(Certificate(service_name='Site', domain='www.exemple.fr',
                               expiry_date=datetime.now(timezone.utc).date() + timedelta(days=40),
                               equipment_id=e.id))
    db.session.commit()
    csv_text = csv_io.export_csv('certificates')
    assert 'equipment' in csv_text.splitlines()[0]   # en-tete
    assert 'SRV-WEB-01' in csv_text


def test_import_certificat_relie_par_nom(app):
    db.session.add(Equipment(name='SRV-SQL-01'))
    db.session.commit()
    contenu = (
        'service_name;domain;issuer;issued_at;expiry_date;auto_renew;priority;description;equipment\n'
        'Base SQL;sql.exemple.fr;Interne;;2026-12-01;non;high;;SRV-SQL-01\n'
    )
    created, errors = csv_io.import_csv('certificates', contenu.encode('utf-8'))
    assert created == 1 and not errors
    cert = Certificate.query.filter_by(service_name='Base SQL').first()
    assert cert.equipment is not None
    assert cert.equipment.name == 'SRV-SQL-01'


def test_import_equipement_inconnu_laisse_vide(app):
    contenu = (
        'service_name;domain;expiry_date;equipment\n'
        'Sans lien;x.exemple.fr;2026-12-01;SERVEUR-FANTOME\n'
    )
    created, errors = csv_io.import_csv('certificates', contenu.encode('utf-8'))
    assert created == 1 and not errors
    assert Certificate.query.filter_by(service_name='Sans lien').first().equipment_id is None


def test_modele_csv_contient_la_colonne_equipement(app):
    for key in ('certificates', 'backups', 'updates'):
        header = csv_io.template_csv(key).splitlines()[0]
        assert 'equipment' in header, f'{key} : colonne equipment absente du modele'
