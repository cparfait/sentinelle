"""Marchés : rattachement N-N aux logiciels, pièces contractuelles, et mise en
concurrence (consultations + devis)."""
from app import db, _migrate_data
from app.models import Contract, ContractItem, Consultation, Quote, Software, Supplier


# ── Un marché couvre autant de logiciels qu'il en couvre réellement ──

def test_un_marche_couvre_plusieurs_logiciels(client):
    a = Software(name='Concerto')
    b = Software(name='Concerto Opus')
    db.session.add_all([a, b])
    db.session.commit()
    client.post('/contracts/create', data={
        'name': 'Marché UGAP 2027', 'kind': 'market', 'nature': 'marche',
        'reference': 'M-2027-04', 'supplier_reference': 'CMD-99812',
        'cost_yearly': '12000', 'cost_max_yearly': '15000', 'cost_total': '48000',
        'start_date': '2027-01-01', 'end_date': '2030-12-31',
        'firm_years': '2', 'renewals': '2', 'renewal_years': '1',
        'software_ids': [str(a.id), str(b.id)]}, follow_redirects=True)
    ct = Contract.query.filter_by(name='Marché UGAP 2027').one()
    assert {s.name for s in ct.software} == {'Concerto', 'Concerto Opus'}
    assert ct.nature == 'marche' and ct.supplier_reference == 'CMD-99812'
    assert ct.cost_max_yearly == 15000 and ct.cost_total == 48000
    assert ct.firm_years == 2 and ct.renewals == 2 and ct.renewal_years == 1
    # Le lien se lit dans les deux sens.
    assert [c.name for c in a.contracts] == ['Marché UGAP 2027']


def test_supprimer_un_logiciel_ne_supprime_pas_le_marche(client):
    """Effacer un acte contractuel par ricochet serait pire que de laisser un
    marché sans rattachement : lui seul dit ce à quoi la collectivité s'engage."""
    sw = Software(name='Éphémère')
    ct = Contract(name='Marché commun')
    db.session.add_all([sw, ct])
    db.session.commit()
    ct.software = [sw]
    db.session.commit()
    client.post(f'/inventory/logiciels/{sw.id}/delete', follow_redirects=True)
    assert Contract.query.filter_by(name='Marché commun').one().is_active is True


def test_periode_et_reconductions_se_lisent_en_francais(client):
    ct = Contract(name='M', start_date=None, end_date=None)
    assert ct.period_label() == ''
    ct.start_date = __import__('datetime').date(2023, 1, 1)
    assert ct.period_label() == 'depuis le 01/01/2023'
    ct.end_date = __import__('datetime').date(2026, 12, 31)
    assert ct.period_label() == 'du 01/01/2023 au 31/12/2026'
    # Zéro est une réponse, l'absence n'en est pas une.
    assert ct.renewal_label() == ''
    ct.renewals = 0
    assert ct.renewal_label() == 'non reconductible'
    ct.renewals, ct.renewal_years = 2, 1
    assert ct.renewal_label() == 'renouvelable 2 fois par période de 1 an'


# ── Les pièces ne décrivent qu'elles-mêmes ──

def test_pieces_du_marche(client):
    ct = Contract(name='Marché RH', cost_yearly=10000)
    db.session.add(ct)
    db.session.commit()
    client.post(f'/contracts/{ct.id}/items/add', data={
        'label': '50 postes', 'kind': 'abonnement', 'cost_yearly': '4000',
        'doc_date': '2026-02-10'}, follow_redirects=True)
    client.post(f'/contracts/{ct.id}/items/add', data={
        'label': 'Module paie', 'kind': 'perpetuelle', 'cost_yearly': '1500'},
        follow_redirects=True)
    assert ct.items.count() == 2
    # Le cumul des pièces est INDICATIF : c'est le montant annuel qui engage.
    assert ct.items_cost() == 5500
    assert ct.cost_yearly == 10000

    piece = ContractItem.query.filter_by(label='Module paie').one()
    client.post(f'/contracts/items/{piece.id}/delete', follow_redirects=True)
    assert ct.items.count() == 1


def test_une_piece_sans_poste_est_refusee(client):
    ct = Contract(name='M')
    db.session.add(ct)
    db.session.commit()
    client.post(f'/contracts/{ct.id}/items/add', data={'cost_yearly': '100'},
                follow_redirects=True)
    assert ct.items.count() == 0


# ── Mise en concurrence ──

def test_consultation_et_devis_retenu(client):
    sw = Software(name='GED')
    s1 = Supplier(name='Éditeur A')
    db.session.add_all([sw, s1])
    db.session.commit()
    client.post(f'/contracts/consultations/{sw.id}/add',
                data={'subject': 'Renouvellement 2027', 'date': '2026-09-01'},
                follow_redirects=True)
    cons = Consultation.query.one()
    assert cons.software_id == sw.id and cons.selected_quote() is None

    client.post(f'/contracts/consultations/{cons.id}/quotes/add',
                data={'supplier_id': str(s1.id), 'amount': '9000', 'date': '2026-09-15'},
                follow_redirects=True)
    # Un fournisseur hors annuaire se saisit au nom : l'historique de la
    # consultation vaut d'être gardé même sans fiche.
    client.post(f'/contracts/consultations/{cons.id}/quotes/add',
                data={'supplier_name': 'SSII locale', 'amount': '7500'},
                follow_redirects=True)
    assert cons.quotes.count() == 2
    libre = Quote.query.filter_by(supplier_name='SSII locale').one()
    assert libre.who() == 'SSII locale' and libre.supplier_id is None

    client.post(f'/contracts/quotes/{libre.id}/select', follow_redirects=True)
    assert cons.selected_quote().id == libre.id


def test_au_plus_un_devis_retenu_par_consultation(client):
    """Deux devis retenus se contrediraient sans que rien ne tranche : marquer
    l'un démarque l'autre dans le même geste."""
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    cons = Consultation(software_id=sw.id, subject='Migration')
    db.session.add(cons)
    db.session.commit()
    a = Quote(consultation_id=cons.id, supplier_name='A', amount=100)
    b = Quote(consultation_id=cons.id, supplier_name='B', amount=200)
    db.session.add_all([a, b])
    db.session.commit()

    client.post(f'/contracts/quotes/{a.id}/select', follow_redirects=True)
    assert a.selected is True and b.selected is False
    client.post(f'/contracts/quotes/{b.id}/select', follow_redirects=True)
    assert a.selected is False and b.selected is True
    assert cons.quotes.filter_by(selected=True).count() == 1


def test_supprimer_une_consultation_emporte_ses_devis(client):
    sw = Software(name='GED')
    db.session.add(sw)
    db.session.commit()
    cons = Consultation(software_id=sw.id, subject='Acquisition')
    db.session.add(cons)
    db.session.commit()
    db.session.add(Quote(consultation_id=cons.id, supplier_name='A'))
    db.session.commit()
    client.post(f'/contracts/consultations/{cons.id}/delete', follow_redirects=True)
    assert Consultation.query.count() == 0 and Quote.query.count() == 0


# ── Reprise de l'ancien lien unique ──

def test_migration_du_contrat_unique_vers_le_lien_multiple(client):
    """L'ancienne colonne software.contract_id est versée une fois dans la table
    de liaison. Elle survit dans les bases existantes, plus rien ne la lit."""
    from sqlalchemy import text, inspect
    cols = {c['name'] for c in inspect(db.engine).get_columns('software')}
    if 'contract_id' not in cols:
        # Base neuve : la colonne n'existe plus, on la recrée pour jouer la reprise.
        db.session.execute(text('ALTER TABLE software ADD COLUMN contract_id INTEGER'))
    ct = Contract(name='Ancienne licence')
    sw = Software(name='Historique')
    db.session.add_all([ct, sw])
    db.session.commit()
    db.session.execute(text('UPDATE software SET contract_id = :c WHERE id = :s'),
                       {'c': ct.id, 's': sw.id})
    db.session.commit()

    _migrate_data()
    db.session.expire_all()
    assert [c.name for c in sw.contracts] == ['Ancienne licence']

    # Idempotent : un second passage ne double pas le lien.
    _migrate_data()
    db.session.expire_all()
    assert sw.contracts.count() == 1


# ── Un marché signé au nom de la société se rattache depuis la fiche logiciel ──

def test_rattacher_un_marche_depuis_la_fiche_logiciel(client):
    """Les marchés ont été saisis au nom de la SOCIÉTÉ qui les signe : la fiche
    logiciel annonçait « Aucun contrat » alors que l'acte existait, rangé sous
    son éditeur. Le lien se pose donc depuis la fiche où le manque se constate."""
    ed = Supplier(name='Arpege')
    db.session.add(ed)
    db.session.commit()
    sw = Software(name='Concerto Opus', supplier_id=ed.id)
    ct = Contract(name='Marché M20-23', supplier_id=ed.id)
    db.session.add_all([sw, ct])
    db.session.commit()

    client.post(f'/contracts/software/{sw.id}/attach',
                data={'contract_id': str(ct.id)}, follow_redirects=True)
    assert [c.name for c in sw.contracts] == ['Marché M20-23']

    # Détacher retire le LIEN, pas l'acte.
    client.post(f'/contracts/{ct.id}/software/{sw.id}/detach', follow_redirects=True)
    assert sw.contracts.count() == 0
    assert Contract.query.filter_by(name='Marché M20-23').one().is_active is True


def test_les_marches_proposes_sont_ceux_de_l_editeur_et_les_orphelins(client):
    from app.software import _marches_rattachables
    ed = Supplier(name='Arpege')
    autre = Supplier(name='Berger-Levrault')
    db.session.add_all([ed, autre])
    db.session.commit()
    sw = Software(name='Concerto Opus', supplier_id=ed.id)
    voisin = Software(name='Voisin', supplier_id=autre.id)
    famille = Contract(name='Marché de la famille', supplier_id=ed.id)
    orphelin = Contract(name='Marché sans logiciel')
    ailleurs = Contract(name="Marché d'un autre éditeur", supplier_id=autre.id)
    db.session.add_all([sw, voisin, famille, orphelin, ailleurs])
    db.session.commit()
    ailleurs.software = [voisin]        # déjà couvert : il appartient à une autre fiche
    db.session.commit()

    noms = {c.name for c in _marches_rattachables(sw)}
    assert noms == {'Marché de la famille', 'Marché sans logiciel'}

    # Une fois rattaché, le marché sort de la liste : on ne le propose plus deux fois.
    famille.software = [sw]
    db.session.commit()
    assert {c.name for c in _marches_rattachables(sw)} == {'Marché sans logiciel'}
