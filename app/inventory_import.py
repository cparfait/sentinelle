"""Import de l'inventaire depuis un classeur Excel (.xlsx) a 3 onglets :
VM / Physiques / NAS. Tolerant : en-tete sur ligne variable, libelles
normalises (accents, retours a la ligne), colonnes inconnues ignorees."""
import io
import unicodedata
from datetime import datetime, date

from app import db
from app.models import Equipment


def _norm(s):
    if s is None:
        return ''
    s = str(s).replace('\n', ' ').replace('\r', ' ')
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


# Regles ordonnees (les plus specifiques d'abord) : (mot-cle, champ, type)
_RULES = [
    ('frequence sauvegarde 1', 'backup1_freq', 'text'),
    ('frequence sauvegarde 2', 'backup2_freq', 'text'),
    ('sauvegarde 1', 'backup1', 'text'),
    ('sauvegarde 2', 'backup2', 'text'),
    ('sauvegarde', 'backup1', 'text'),
    ('derniere maj', 'os_last_update', 'date'),
    ('os / version', 'os', 'text'),
    ('os/version', 'os', 'text'),
    ('version', 'os_version', 'text'),
    ('environnement', 'environment', 'env'),
    ('serveur hote', 'host_server', 'text'),
    ('hyperviseur', 'hypervisor', 'text'),
    ('adresse ip', 'ip_address', 'text'),
    ('masque', 'netmask', 'text'),
    ('maque', 'netmask', 'text'),
    ('vlan', 'vlan', 'text'),
    ('cyberwatch', 'cyberwatch', 'bool'),
    ('ninja', 'ninja_one', 'bool'),
    ('supervision', 'supervision', 'superv'),
    ('vcpu', 'vcpu', 'int'),
    ('ram', 'ram_go', 'float'),
    ('stockage hdd 1', 'hdd1_go', 'float'),
    ('stockage hdd 2', 'hdd2_go', 'float'),
    ('stockage hdd 3', 'hdd3_go', 'float'),
    ('hdd 1', 'hdd1_go', 'float'),
    ('hdd 2', 'hdd2_go', 'float'),
    ('hdd 3', 'hdd3_go', 'float'),
    ('role principal', 'role_principal', 'text'),
    ('logiciels', 'business_software', 'text'),
    ('services utilisateurs', 'user_services', 'text'),
    ('criticite', 'criticality', 'crit'),
    ('constructeur', 'manufacturer_model', 'text'),
    ('modele', 'manufacturer_model', 'text'),
    ('numero de serie', 'serial_number', 'text'),
    ('n de serie', 'serial_number', 'text'),
    ('serie', 'serial_number', 'text'),
    ('date achat', 'purchase_date', 'date'),
    ('mise en service', 'purchase_date', 'date'),
    ('fin de garantie', 'warranty_end', 'date'),
    ('garantie', 'warranty_end', 'date'),
    ('pra', 'pra_pca', 'text'),
    ('pca', 'pra_pca', 'text'),
    ('protocoles', 'protocols', 'text'),
    ('acces', 'access', 'text'),
    ('capacite', 'capacity_to', 'float'),
    ('espace utilise', 'used_to', 'float'),
    ('utilise', 'used_to', 'float'),
    ('raid', 'raid', 'text'),
    ('contrat de maintenance', 'maintenance_contract', 'text'),
    ('usage principal', 'usage', 'text'),
    ('donnees stockees', 'usage', 'text'),
    ('usage', 'usage', 'text'),
    ('observations', 'observations', 'text'),
    ('os', 'os', 'text'),
    ('hostname', 'name', 'text'),
    ("nom d'hote", 'name', 'text'),
    ('nom', 'name', 'text'),
]


def _match_field(h):
    for kw, field, typ in _RULES:
        if kw in h:
            return field, typ
    return None


def _detect_kind(title):
    t = _norm(title)
    if 'vm' in t:
        return 'vm'
    if 'phys' in t:
        return 'physical'
    if 'nas' in t:
        return 'nas'
    return None


def _find_header_row(rows):
    best, best_score = None, 0
    for i, r in enumerate(rows[:6]):
        score = sum(1 for c in r if _match_field(_norm(c)))
        if score > best_score:
            best_score, best = score, i
    return best if best_score >= 3 else None


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_float(v):
    if v in (None, ''):
        return None
    try:
        return float(str(v).replace(',', '.').split()[0])
    except (ValueError, IndexError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


def _to_bool(v):
    n = _norm(v)
    if not n:
        return False
    return n not in ('non', 'no', '0', 'false', 'n')


def _to_crit(v):
    n = _norm(v)
    for ch in n:
        if ch in '1234':
            return int(ch)
    return None


def _to_env(v):
    n = _norm(v)
    if 'prepro' in n or 'preprod' in n:
        return 'preprod'
    if 'prod' in n:
        return 'prod'
    if 'dev' in n or 'recet' in n:
        return 'dev'
    return None


def _build_colmap(headers):
    colmap = {}
    for idx, h in enumerate(headers):
        m = _match_field(_norm(h))
        if m:
            colmap[idx] = m
    return colmap


def _assign(eq, value, field, typ, kind):
    if typ == 'text':
        v = str(value).strip() if value not in (None, '') else None
        if v:
            setattr(eq, field, v)
    elif typ == 'date':
        d = _to_date(value)
        if d:
            setattr(eq, field, d)
    elif typ == 'float':
        f = _to_float(value)
        if f is not None:
            setattr(eq, field, f)
    elif typ == 'int':
        i = _to_int(value)
        if i is not None:
            setattr(eq, field, i)
    elif typ == 'bool':
        setattr(eq, field, _to_bool(value))
    elif typ == 'crit':
        c = _to_crit(value)
        if c is not None:
            eq.criticality = c
    elif typ == 'env':
        e = _to_env(value)
        if e:
            eq.environment = e
    elif typ == 'superv':
        if kind == 'vm':
            eq.supervised = _to_bool(value)
        else:
            v = str(value).strip() if value not in (None, '') else None
            if v:
                eq.supervision = v


def import_workbook(fileobj):
    """Lit le classeur et cree les equipements. Retourne (nb_crees, rapport)."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(fileobj.read()), data_only=True, read_only=True)
    created = 0
    notes = []
    for ws in wb.worksheets:
        kind = _detect_kind(ws.title)
        if not kind:
            notes.append(f'« {ws.title} » ignoré (type inconnu)')
            continue
        rows = list(ws.iter_rows(values_only=True))
        hidx = _find_header_row(rows)
        if hidx is None:
            notes.append(f'« {ws.title} » : en-tête introuvable')
            continue
        colmap = _build_colmap(rows[hidx])
        n = 0
        for r in rows[hidx + 1:]:
            if not any(c not in (None, '') for c in r):
                continue
            eq = Equipment(kind=kind)
            for idx, (field, typ) in colmap.items():
                if idx < len(r):
                    _assign(eq, r[idx], field, typ, kind)
            # Repli : onglets Physiques/NAS sans colonne « Nom »
            if not (eq.name and eq.name.strip()):
                eq.name = (eq.serial_number or eq.ip_address or eq.host_server
                           or eq.manufacturer_model or '').strip() or None
            if not eq.name:
                continue
            db.session.add(eq)
            created += 1
            n += 1
        notes.append(f'{ws.title} : {n} ligne(s)')
    return created, ' · '.join(notes)
