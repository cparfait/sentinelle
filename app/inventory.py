from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for, request, flash)
from flask_login import login_required, current_user
from app import db
from app.models import (Equipment, EQUIPMENT_KIND_LABELS, ENVIRONMENT_LABELS,
                        CRITICALITY_LABELS)
from app.decorators import require_edit, require_delete, view_guard
from app.audit import record as audit_record

bp = Blueprint('inventory', __name__)

KIND_CHOICES = [('vm', 'VM'), ('physical', 'Serveur physique'), ('nas', 'NAS')]
ENV_CHOICES = [('', '—'), ('prod', 'Production'), ('preprod', 'Préproduction'), ('dev', 'Développement')]
SEARCH_FIELDS = ['name', 'os', 'os_version', 'ip_address', 'host_server', 'hypervisor',
                 'role_principal', 'business_software', 'serial_number',
                 'manufacturer_model', 'usage', 'observations']


@bp.before_request
def _guard_view():
    return view_guard('inventory')


def _pd(v):
    try:
        return datetime.strptime(v, '%Y-%m-%d').date() if v else None
    except (ValueError, TypeError):
        return None


def _pf(v):
    try:
        return float(str(v).replace(',', '.')) if v not in (None, '') else None
    except ValueError:
        return None


def _pi(v):
    try:
        return int(v) if v not in (None, '') else None
    except (ValueError, TypeError):
        return None


def _txt(f, key):
    return (f.get(key, '') or '').strip() or None


def _apply_form(eq, f):
    eq.kind = f.get('kind', 'vm') if f.get('kind') in ('vm', 'physical', 'nas') else 'vm'
    eq.name = (f.get('name', '') or '').strip()
    eq.environment = f.get('environment') or None
    eq.criticality = _pi(f.get('criticality'))
    eq.os = _txt(f, 'os')
    eq.os_version = _txt(f, 'os_version')
    eq.os_last_update = _pd(f.get('os_last_update'))
    eq.supervision = _txt(f, 'supervision')
    eq.supervised = bool(f.get('supervised'))
    eq.cyberwatch = bool(f.get('cyberwatch'))
    eq.ninja_one = bool(f.get('ninja_one'))
    eq.ip_address = _txt(f, 'ip_address')
    eq.netmask = _txt(f, 'netmask')
    eq.vlan = _txt(f, 'vlan')
    eq.host_server = _txt(f, 'host_server')
    eq.hypervisor = _txt(f, 'hypervisor')
    eq.vcpu = _pi(f.get('vcpu'))
    eq.ram_go = _pf(f.get('ram_go'))
    eq.hdd1_go = _pf(f.get('hdd1_go'))
    eq.hdd2_go = _pf(f.get('hdd2_go'))
    eq.hdd3_go = _pf(f.get('hdd3_go'))
    eq.manufacturer_model = _txt(f, 'manufacturer_model')
    eq.serial_number = _txt(f, 'serial_number')
    eq.purchase_date = _pd(f.get('purchase_date'))
    eq.warranty_end = _pd(f.get('warranty_end'))
    eq.maintenance_contract = _txt(f, 'maintenance_contract')
    eq.protocols = _txt(f, 'protocols')
    eq.access = _txt(f, 'access')
    eq.capacity_to = _pf(f.get('capacity_to'))
    eq.used_to = _pf(f.get('used_to'))
    eq.raid = _txt(f, 'raid')
    eq.role_principal = _txt(f, 'role_principal')
    eq.business_software = _txt(f, 'business_software')
    eq.user_services = _txt(f, 'user_services')
    eq.usage = _txt(f, 'usage')
    eq.pra_pca = _txt(f, 'pra_pca')
    eq.backup1 = _txt(f, 'backup1')
    eq.backup1_freq = _txt(f, 'backup1_freq')
    eq.backup2 = _txt(f, 'backup2')
    eq.backup2_freq = _txt(f, 'backup2_freq')
    eq.observations = _txt(f, 'observations')


def _render_form(item):
    return render_template('inventory/form.html', item=item, kind_choices=KIND_CHOICES,
                           env_choices=ENV_CHOICES, crit_labels=CRITICALITY_LABELS)


@bp.route('/')
@login_required
def list():
    items = Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all()
    q = request.args.get('q', '').strip()
    kind = request.args.get('kind', '').strip()
    # Filtre avance
    f = {
        'environment': request.args.get('environment', '').strip(),
        'criticality': request.args.get('criticality', '').strip(),
        'status': request.args.get('status', '').strip(),
        'os': request.args.get('os', '').strip(),
        'hypervisor': request.args.get('hypervisor', '').strip(),
        'supervision': request.args.get('supervision', '').strip(),   # yes / no
        'warranty': request.args.get('warranty', '').strip(),         # expiring / expired
        'no_backup': request.args.get('no_backup', '').strip(),       # 1
    }
    if kind in ('vm', 'physical', 'nas'):
        items = [e for e in items if e.kind == kind]
    from app.paging import paginate, text_search
    items = text_search(items, q, SEARCH_FIELDS)

    def keep(e):
        if f['environment'] and e.environment != f['environment']:
            return False
        if f['criticality'] and str(e.criticality or '') != f['criticality']:
            return False
        if f['status'] and e.computed_status() != f['status']:
            return False
        if f['os'] and f['os'].lower() not in (e.os or '').lower():
            return False
        if f['hypervisor'] and f['hypervisor'].lower() not in (e.hypervisor or '').lower():
            return False
        if f['supervision'] == 'yes' and not (e.supervised or e.supervision):
            return False
        if f['supervision'] == 'no' and (e.supervised or e.supervision):
            return False
        if f['no_backup'] == '1' and (e.backup1 or e.backup2):
            return False
        if f['warranty'] in ('expiring', 'expired'):
            d = e.warranty_days_left()
            if d is None:
                return False
            if f['warranty'] == 'expired' and d >= 0:
                return False
            if f['warranty'] == 'expiring' and not (0 <= d <= 90):
                return False
        return True

    items = [e for e in items if keep(e)]
    active_filters = sum(1 for v in f.values() if v)
    rank = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    items.sort(key=lambda e: rank.get(e.computed_status(), 4))
    items, page, pages, total = paginate(items)
    counts = {k: Equipment.query.filter_by(is_active=True, kind=k).count()
              for k in ('vm', 'physical', 'nas')}
    return render_template('inventory/list.html', items=items, q=q, kind=kind, counts=counts,
                           kind_labels=EQUIPMENT_KIND_LABELS, crit_labels=CRITICALITY_LABELS,
                           filters=f, active_filters=active_filters,
                           env_choices=ENV_CHOICES, crit_labels_dict=CRITICALITY_LABELS,
                           page=page, pages=pages, total=total)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_edit
def create():
    if request.method == 'POST':
        eq = Equipment()
        _apply_form(eq, request.form)
        if not eq.name:
            flash('Le nom est obligatoire.', 'danger')
            return _render_form(None)
        db.session.add(eq)
        db.session.commit()
        audit_record('creation inventaire', detail=f'{eq.name} ({eq.kind_label()})', category='inventory')
        flash('Équipement ajouté', 'success')
        return redirect(url_for('inventory.detail', id=eq.id))
    return _render_form(None)


@bp.route('/<int:id>')
@login_required
def detail(id):
    item = Equipment.query.get_or_404(id)
    return render_template('inventory/detail.html', item=item,
                           crit_labels=CRITICALITY_LABELS)


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@require_edit
def edit(id):
    item = Equipment.query.get_or_404(id)
    if request.method == 'POST':
        _apply_form(item, request.form)
        if not item.name:
            flash('Le nom est obligatoire.', 'danger')
            return _render_form(item)
        db.session.commit()
        audit_record('modification inventaire', detail=item.name, category='inventory')
        flash('Équipement modifié', 'success')
        return redirect(url_for('inventory.detail', id=id))
    return _render_form(item)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@require_delete
def delete(id):
    item = Equipment.query.get_or_404(id)
    item.is_active = False
    db.session.commit()
    audit_record('suppression inventaire', detail=item.name, category='inventory')
    flash('Équipement supprimé', 'success')
    return redirect(url_for('inventory.list'))


@bp.route('/import', methods=['GET', 'POST'])
@login_required
@require_edit
def import_xlsx():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.lower().endswith(('.xlsx', '.xlsm')):
            flash('Veuillez fournir un fichier Excel (.xlsx).', 'danger')
            return redirect(url_for('inventory.import_xlsx'))
        from app.inventory_import import import_workbook
        try:
            created, report = import_workbook(file)
            db.session.commit()
            audit_record('import inventaire', detail=f'{created} equipement(s)', category='inventory')
            flash(f'{created} équipement(s) importé(s). {report}', 'success')
            return redirect(url_for('inventory.list'))
        except Exception as e:
            db.session.rollback()
            flash(f"Échec de l'import : {e}", 'danger')
            return redirect(url_for('inventory.import_xlsx'))
    return render_template('inventory/import.html')
