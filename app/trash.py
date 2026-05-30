"""Corbeille : éléments désactivés (is_active=False) restaurables par catégorie."""
from app import db
from app.models import (Account, AccountHistory, Certificate, CertificateHistory,
                        Domain, DomainHistory, Backup, BackupHistory, TestTask,
                        TestHistory, AccessReview, ReviewHistory, SystemUpdate,
                        UpdateHistory)

SPECS = {
    'account': {'model': Account, 'cat': 'accounts', 'hist': AccountHistory,
                'fk': 'account_id', 'label': 'Comptes',
                'name': lambda o: f'{o.service_name} ({o.username})'},
    'certificate': {'model': Certificate, 'cat': 'certificates', 'hist': CertificateHistory,
                    'fk': 'certificate_id', 'label': 'Certificats',
                    'name': lambda o: f'{o.service_name} - {o.domain}'},
    'domain': {'model': Domain, 'cat': 'domains', 'hist': DomainHistory,
               'fk': 'domain_id', 'label': 'Domaines', 'name': lambda o: o.name},
    'backup': {'model': Backup, 'cat': 'backups', 'hist': BackupHistory,
               'fk': 'backup_id', 'label': 'Backups', 'name': lambda o: o.service_name},
    'test': {'model': TestTask, 'cat': 'tests', 'hist': TestHistory,
             'fk': 'test_id', 'label': 'Tests', 'name': lambda o: o.name},
    'review': {'model': AccessReview, 'cat': 'reviews', 'hist': ReviewHistory,
               'fk': 'review_id', 'label': 'Revue de droits', 'name': lambda o: o.application},
    'update': {'model': SystemUpdate, 'cat': 'updates', 'hist': UpdateHistory,
               'fk': 'update_id', 'label': 'Mises à jour', 'name': lambda o: o.name},
}


def list_trashed(user):
    """Groupes d'éléments supprimés pour les catégories que l'utilisateur peut éditer."""
    groups = []
    for etype, s in SPECS.items():
        if not user.can_edit(s['cat']):
            continue
        items = s['model'].query.filter_by(is_active=False).order_by(
            s['model'].updated_at.desc()).all()
        if items:
            groups.append({
                'etype': etype, 'label': s['label'],
                'items': [{'id': o.id, 'name': s['name'](o),
                           'date': o.updated_at} for o in items],
            })
    return groups


def restore(user, etype, entity_id, performed_by):
    s = SPECS.get(etype)
    if not s or not str(entity_id).isdigit() or not user.can_edit(s['cat']):
        return False
    obj = s['model'].query.get(int(entity_id))
    if not obj:
        return False
    obj.is_active = True
    db.session.add(s['hist'](**{s['fk']: obj.id, 'action': 'restored',
                                'comment': 'Restaure depuis la corbeille',
                                'performed_by': performed_by}))
    db.session.commit()
    return True
