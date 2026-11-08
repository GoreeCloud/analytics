"""Offline, backup-gated initial binding of a site to one independently vetted tenant.

This does NOT authenticate a subject, validate Identity membership, or authorize
any HTTP API. Operators must independently establish tenant/site/principal
ownership before using this command on a stopped development database.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from .backup import backup_database
from .ownership import PERMISSIONS, has_site_permission
from .schema_audit import inspect_schema

_SITE = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_TENANT = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SUBJECT = re.compile(r"[A-Za-z0-9_.:@/-]{1,255}\Z")


def _validated(site_id: str, tenant_id: str, subject_id: str,
               permissions: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if (type(site_id) is not str or not _SITE.fullmatch(site_id) or
            type(tenant_id) is not str or not _TENANT.fullmatch(tenant_id) or
            type(subject_id) is not str or not _SUBJECT.fullmatch(subject_id)):
        raise ValueError("Valid, exact site, tenant, and principal identifiers are required")
    if (type(permissions) not in (tuple, list) or not permissions or
            len(permissions) > len(PERMISSIONS) or
            any(type(item) is not str or item not in PERMISSIONS for item in permissions) or
            len(set(permissions)) != len(permissions)):
        raise ValueError("Specify unique, explicit site permissions from the allowlist")
    return tuple(sorted(permissions))


def _read_only(path: Path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    db.execute('PRAGMA query_only=ON')
    return db


def preview_owner_binding(database: str | Path, site_id: str, tenant_id: str,
                          subject_id: str, permissions: list[str] | tuple[str, ...]) -> dict:
    """Read-only preview; an existing owner always blocks initial assignment."""
    permissions = _validated(site_id, tenant_id, subject_id, permissions)
    audit = inspect_schema(database)
    if audit['status'] != 'ready' or audit['user_version'] != 2:
        raise ValueError('Database must be migrated to the exact v2 ownership schema')
    path = Path(database).expanduser().absolute()
    with closing(_read_only(path)) as db:
        site = db.execute('SELECT id FROM sites WHERE id=?', (site_id,)).fetchone()
        if site is None:
            raise ValueError('Unknown site; no ownership assigned')
        if db.execute('SELECT 1 FROM site_owners WHERE site_id=?', (site_id,)).fetchone():
            raise ValueError('Site already has a registered owner; reassignment is prohibited')
    return {'mode': 'preview', 'site_id': site_id, 'tenant_id': tenant_id,
            'subject_id': subject_id, 'permissions': list(permissions),
            'requires_verified_independent_ownership_evidence': True,
            'requires_stopped_writers': True, 'requires_verified_backup': True}


def apply_owner_binding(database: str | Path, site_id: str, tenant_id: str,
                        subject_id: str, permissions: list[str] | tuple[str, ...],
                        backup_to: str | Path, confirm_site_id: str,
                        confirm_tenant_id: str) -> dict:
    """Assign once; refusal and rollback protect existing owner or backup."""
    plan = preview_owner_binding(database, site_id, tenant_id, subject_id, permissions)
    if confirm_site_id != site_id or confirm_tenant_id != tenant_id:
        raise ValueError('Confirmation must exactly match site ID and tenant ID')
    source = Path(database).expanduser().absolute()
    evidence = backup_database(source, backup_to)
    backup_path = Path(evidence['destination'])
    with closing(_read_only(backup_path)) as snapshot:
        snapshot_site = snapshot.execute('SELECT * FROM sites WHERE id=?', (site_id,)).fetchone()
        if snapshot_site is None or snapshot.execute(
                'SELECT 1 FROM site_owners WHERE site_id=?', (site_id,)).fetchone():
            raise RuntimeError('Owner/site changed before backup; no assignment made')
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with closing(sqlite3.connect(source, timeout=10)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            current_site = db.execute('SELECT * FROM sites WHERE id=?', (site_id,)).fetchone()
            if current_site != snapshot_site or db.execute(
                    'SELECT 1 FROM site_owners WHERE site_id=?', (site_id,)).fetchone():
                raise RuntimeError('Owner/site changed since verified backup; no assignment made')
            db.execute('INSERT INTO site_owners(site_id,tenant_id,assigned_at,assigned_by) '
                       'VALUES(?,?,?,?)', (site_id, tenant_id, now, 'offline-operator'))
            db.executemany('INSERT INTO site_permissions(site_id,subject_id,permission,granted_at) '
                           'VALUES(?,?,?,?)', [(site_id, subject_id, p, now) for p in plan['permissions']])
            for permission in plan['permissions']:
                if not has_site_permission(db,site_id=site_id,trusted_tenant_id=tenant_id,
                                           trusted_subject_id=subject_id,permission=permission):
                    raise RuntimeError('Ownership permission verification failed; rolling back')
            db.commit()
        except Exception:
            db.rollback()
            raise
    if inspect_schema(source)['status'] != 'ready':
        raise RuntimeError('Post-assignment schema audit failed; preserve backup')
    return {**plan, 'mode': 'applied', 'verified_backup': evidence,
            'cryptographic_identity_authentication_not_performed': True}


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline initial Analytics site owner binding')
    parser.add_argument('--database', required=True)
    parser.add_argument('--site-id', required=True)
    parser.add_argument('--tenant-id', required=True)
    parser.add_argument('--subject-id', required=True)
    parser.add_argument('--permissions', required=True, help='Comma-separated explicit site permissions')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-to')
    parser.add_argument('--confirm-site-id')
    parser.add_argument('--confirm-tenant-id')
    opts = parser.parse_args()
    if opts.apply and (not opts.backup_to or not opts.confirm_site_id or not opts.confirm_tenant_id):
        parser.error('--apply requires --backup-to, --confirm-site-id and --confirm-tenant-id')
    if not opts.apply and (opts.backup_to or opts.confirm_site_id or opts.confirm_tenant_id):
        parser.error('Backup and confirmation options require --apply')
    permissions = opts.permissions.split(',')
    try:
        result = (apply_owner_binding(opts.database, opts.site_id, opts.tenant_id,
                                     opts.subject_id, permissions, opts.backup_to,
                                     opts.confirm_site_id, opts.confirm_tenant_id)
                  if opts.apply else
                  preview_owner_binding(opts.database, opts.site_id, opts.tenant_id,
                                        opts.subject_id, permissions))
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as err:
        parser.error(str(err))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
