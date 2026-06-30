"""Corbeille : éléments désactivés (is_active=False) restaurables par catégorie."""
from app import db
from app.models import (Account, AccountHistory, Certificate, CertificateHistory,
                        Domain, DomainHistory, Backup, BackupHistory, TestTask,
                        TestHistory, AccessReview, ReviewHistory, SystemUpdate,
                        UpdateHistory, Equipment, Supplier, Contract, ContractHistory)

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
    # Pas de modèle d'historique dédié pour l'inventaire : la restauration est
    # tracée via le journal d'audit (ActionLog) par la route appelante.
    'equipment': {'model': Equipment, 'cat': 'inventory', 'hist': None,
                  'fk': None, 'label': 'Inventaire', 'name': lambda o: o.name},
    'contract': {'model': Contract, 'cat': 'contracts', 'hist': ContractHistory,
                 'fk': 'contract_id', 'label': 'Contrats', 'name': lambda o: o.name},
    'supplier': {'model': Supplier, 'cat': 'contracts', 'hist': None,
                 'fk': None, 'label': 'Fournisseurs', 'name': lambda o: o.name},
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
                'can_purge': user.can_delete(s['cat']),
                'items': [{'id': o.id, 'name': s['name'](o),
                           'date': o.updated_at} for o in items],
            })
    return groups


def _purge_obj(etype, obj):
    """Suppression definitive d'un objet + nettoyage du snooze associe."""
    from app.snooze import clear_snooze
    clear_snooze(etype, obj.id)
    if etype == 'equipment':
        # SQLite n'applique pas les FK : on detache explicitement les elements
        # lies (vue 360°) pour ne pas laisser d'equipment_id orphelin.
        for model in (Certificate, Backup, SystemUpdate, Contract):
            model.query.filter_by(equipment_id=obj.id).update({'equipment_id': None})
    if etype == 'supplier':
        # Meme principe : detacher les references avant suppression definitive.
        Equipment.query.filter_by(supplier_id=obj.id).update({'supplier_id': None})
        Contract.query.filter_by(supplier_id=obj.id).update({'supplier_id': None})
    db.session.delete(obj)


def purge_one(user, etype, entity_id):
    """Suppression definitive d'un element. Retourne (label, nom) ou None."""
    s = SPECS.get(etype)
    if not s or not str(entity_id).isdigit() or not user.can_delete(s['cat']):
        return None
    obj = s['model'].query.filter_by(id=int(entity_id), is_active=False).first()
    if not obj:
        return None
    name = s['name'](obj)
    _purge_obj(etype, obj)
    db.session.commit()
    return (s['label'], name)


def purge_all(user):
    """Supprime definitivement tous les elements en corbeille des categories
    sur lesquelles l'utilisateur a le droit de suppression. Retourne le total."""
    total = 0
    for etype, s in SPECS.items():
        if not user.can_delete(s['cat']):
            continue
        for obj in s['model'].query.filter_by(is_active=False).all():
            _purge_obj(etype, obj)
            total += 1
    if total:
        db.session.commit()
    return total


def restore(user, etype, entity_id, performed_by):
    """Restaure un element. Retourne (label, nom) ou None."""
    s = SPECS.get(etype)
    if not s or not str(entity_id).isdigit() or not user.can_edit(s['cat']):
        return None
    obj = db.session.get(s['model'], int(entity_id))
    # On ne restaure que ce qui est reellement en corbeille : sinon on
    # reactiverait inutilement un element actif et on tracerait un faux
    # « restaure » dans l'historique.
    if not obj or obj.is_active:
        return None
    obj.is_active = True
    name = s['name'](obj)
    if s['hist'] is not None:
        db.session.add(s['hist'](**{s['fk']: obj.id, 'action': 'restored',
                                    'comment': 'Restaure depuis la corbeille',
                                    'performed_by': performed_by}))
    db.session.commit()
    return (s['label'], name)
