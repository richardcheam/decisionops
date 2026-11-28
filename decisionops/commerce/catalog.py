"""Shop-scoped catalog investigation and idempotent image relinks."""

from hashlib import sha256
import json
from pathlib import Path
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock, identifier
from .catalog_policy import assess
from .read_tools import canonical

ROOT = Path(__file__).resolve().parents[2] / 'data/commerce/catalog'
STORE = 'demo-store'


def seed(engine):
    with (ROOT / 'cases.json').open() as source:
        fixtures = json.load(source)
    with engine.begin() as c:
        for row in fixtures:
            if row['split'] != 'demo':
                continue
            c.execute(insert(db.catalog_listings).values(
                store_id=STORE, sku=row['sku'], title=row['title'],
                current_image_id=row['current_image_id'], version=1,
                image_mappings=row['images'], supplier_record=row['supplier'],
            ).on_conflict_do_nothing())
            c.execute(insert(db.catalog_cases).values(
                store_id=STORE, id=row['id'], sku=row['sku'], status='open',
                reason='Check the current image, verified SKU mapping, and supplier record.',
            ).on_conflict_do_nothing())


def _case_filter(table, store, case_id):
    return (table.c.store_id == store, table.c.id == case_id)


def _listing_filter(store, sku):
    return (db.catalog_listings.c.store_id == store, db.catalog_listings.c.sku == sku)


def _load(c, store, case_id, *, lock=False):
    query = sa.select(db.catalog_cases).where(*_case_filter(db.catalog_cases, store, case_id))
    case = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if case is None:
        raise LookupError('Catalog case not found')
    query = sa.select(db.catalog_listings).where(*_listing_filter(store, case['sku']))
    listing = c.execute(query.with_for_update() if lock else query).mappings().one()
    return case, listing


def _snapshot(listing):
    return {
        'sku': listing['sku'], 'current_image_id': listing['current_image_id'],
        'images': listing['image_mappings'], 'supplier': listing['supplier_record'],
        'version': listing['version'],
    }


def _receipt(c, case):
    row = c.execute(sa.select(db.catalog_relinks).where(
        db.catalog_relinks.c.store_id == case['store_id'],
        db.catalog_relinks.c.case_id == case['id'],
    )).mappings().one_or_none()
    if row is None:
        return None
    return {name: row[name] for name in ('saved_image_id', 'listing_version')}


def _view(c, case, listing):
    proposal = case['proposal'] or {}
    return {
        'id': case['id'], 'sku': case['sku'], 'title': listing['title'],
        'status': case['status'], 'reason': case['reason'],
        'current_image_id': listing['current_image_id'],
        'proposed_image_id': proposal.get('proposed_image_id'),
        'proposal_hash': case['proposal_hash'], 'evidence': _snapshot(listing),
        'receipt': _receipt(c, case),
    }


def queue(c, store):
    ids = c.execute(sa.select(db.catalog_cases.c.id).where(
        db.catalog_cases.c.store_id == store,
    ).order_by(db.catalog_cases.c.id)).scalars().all()
    return [detail(c, store, identity) for identity in ids]


def detail(c, store, case_id):
    return _view(c, *_load(c, store, case_id))


def _asset_path(image_id):
    if not isinstance(image_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', image_id):
        raise LookupError('Catalog image not found')
    file = ROOT / 'images' / (image_id + '.png')
    if not file.is_file():
        raise LookupError('Catalog image not found')
    return file


def image(c, store, case_id, image_id):
    _, listing = _load(c, store, case_id)
    scoped = {row['id'] for row in listing['image_mappings']} | {listing['current_image_id']}
    if image_id not in scoped:
        raise LookupError('Catalog image not found')
    return _asset_path(image_id).read_bytes()


def _change(c, case, **values):
    return c.execute(db.catalog_cases.update().where(
        *_case_filter(db.catalog_cases, case['store_id'], case['id']),
    ).values(**values).returning(db.catalog_cases)).mappings().one()


def _decision(listing):
    try:
        action, target, reason = assess(_snapshot(listing))
        if target is not None:
            _asset_path(target)
        return action, target, reason
    except (KeyError, TypeError, LookupError):
        return 'review', None, 'Verify the image record and asset before changing the listing.'


def _hash(proposal):
    return sha256(canonical(proposal).encode()).hexdigest()


def investigate(c, store, case_id):
    case, listing = _load(c, store, case_id, lock=True)
    if case['status'] == 'confirmed':
        return _view(c, case, listing)
    action, target, reason = _decision(listing)
    proposal = None
    if action == 'relink':
        proposal = {
            'id': identifier('CATALOG-PROPOSAL'), 'case_id': case_id, 'store_id': store,
            'proposed_image_id': target, 'source': _snapshot(listing),
        }
    case = _change(c, case, status={'keep': 'current', 'review': 'review', 'relink': 'proposed'}[action],
                   reason=reason, proposal=proposal, proposal_hash=_hash(proposal) if proposal else None,
                   approved_by=None)
    return _view(c, case, listing)


def _matches(case, listing):
    action, target, _ = _decision(listing)
    proposal = case['proposal']
    return (action == 'relink' and target == proposal['proposed_image_id']
            and proposal['source'] == _snapshot(listing) and _hash(proposal) == case['proposal_hash'])


def _stale(c, case, listing):
    _, _, reason = _decision(listing)
    case = _change(c, case, status='review', reason='Evidence changed. Check the latest records before proposing another change. ' + reason,
                   proposal=None, proposal_hash=None, approved_by=None)
    return _view(c, case, listing)


def approve(c, store, case_id, proposal_hash, actor):
    case, listing = _load(c, store, case_id, lock=True)
    if case['status'] not in ('proposed', 'approved') or case['proposal_hash'] != proposal_hash:
        raise ValueError('The exact current catalog proposal is required')
    if not _matches(case, listing):
        return _stale(c, case, listing)
    if case['status'] != 'approved':
        case = _change(c, case, status='approved', approved_by=actor)
    return _view(c, case, listing)


def confirm(c, store, case_id, proposal_hash, actor):
    case, listing = _load(c, store, case_id, lock=True)
    if case['status'] not in ('approved', 'confirmed') or case['proposal_hash'] != proposal_hash:
        raise ValueError('The exact approved catalog proposal is required')
    if case['status'] == 'confirmed':
        return _view(c, case, listing)
    if not _matches(case, listing):
        return _stale(c, case, listing)
    sku, target, version = listing['sku'], case['proposal']['proposed_image_id'], listing['version']
    c.execute(db.catalog_listings.update().where(
        *_listing_filter(store, sku), db.catalog_listings.c.version == version,
    ).values(current_image_id=target, version=version + 1))
    _, saved = _load(c, store, case_id)
    if (saved['current_image_id'], saved['version']) != (target, version + 1):
        raise RuntimeError('Catalog relink verification failed')
    c.execute(db.catalog_relinks.insert().values(
        store_id=store, case_id=case_id, proposal_hash=proposal_hash,
        previous_image_id=listing['current_image_id'], saved_image_id=target,
        listing_version=saved['version'], approved_by=case['approved_by'],
        confirmed_by=actor, created_at=clock(c),
    ))
    case = _change(c, case, status='confirmed', reason='The saved image and listing version were verified.')
    return _view(c, case, saved)
