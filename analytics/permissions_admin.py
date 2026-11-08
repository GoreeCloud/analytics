"""Offline, backup-gated revocation of ONE existing Analytics site permission.

This is not an HTTP endpoint, JWT revocation, or a live Identity user/group
management service. Operators must stop writers and independently verify the
site, tenant, subject, permission, and scope before applying.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .backup import backup_database
from .ownership import has_site_permission
from .ownership_admin import _validated
from .schema_audit import inspect_schema


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    connection.execute('PRAGMA query_only=ON')
    return connection


def _snapshot(db: sqlite3.Connection, site_id: str, tenant_id: str,
              subject_id: str, permission: str) -> tuple:
    owner = db.execute('SELECT tenant_id, assigned_at, assigned_by FROM site_owners '
                       'WHERE site_id=?', (site_id,)).fetchone()
    if owner is None or owner[0] != tenant_id:
        raise ValueError('Exact site ownership binding does not exist')
    row = db.execute('SELECT granted_at FROM site_permissions WHERE site_id=? '
                     'AND subject_id=? AND permission=?',
                     (site_id, subject_id, permission)).fetchone()
    if row is None:
        raise ValueError('Exact permission grant does not exist')
    count = db.execute('SELECT COUNT(*) FROM site_permissions WHERE site_id=?',
                       (site_id,)).fetchone()[0]
    return (tuple(owner), row[0], count)


def preview_permission_revocation(database: str | Path, site_id: str,
                                  tenant_id: str, subject_id: str,
                                  permission: str) -> dict:
    """Read-only preview; never mutate or auto-revoke a grant."""
    _validated(site_id, tenant_id, subject_id, [permission])
    audit = inspect_schema(database)
    if audit['status'] != 'ready' or audit['user_version'] != 2:
        raise ValueError('Database must pass exact SQLite v2 ownership schema audit')
    path = Path(database).expanduser().absolute()
    with closing(_readonly(path)) as db:
        _, _, count = _snapshot(db, site_id, tenant_id, subject_id, permission)
    return {'mode': 'preview', 'site_id': site_id, 'tenant_id': tenant_id,
            'subject_id': subject_id, 'permission': permission,
            'site_permissions_before': count,
            'requires_stopped_writers': True, 'verified_backup_required': True,
            'does_not_revoke_issued_oauth_tokens': True}


def apply_permission_revocation(database: str | Path, site_id: str,
                                tenant_id: str, subject_id: str,
                                permission: str, backup_to: str | Path,
                                confirm_site_id: str, confirm_tenant_id: str,
                                confirm_subject_id: str, confirm_permission: str) -> dict:
    """Revoke exactly one permission after full confirmations and verified backup."""
    plan = preview_permission_revocation(database, site_id, tenant_id,
                                         subject_id, permission)
    if (confirm_site_id != site_id or confirm_tenant_id != tenant_id or
            confirm_subject_id != subject_id or confirm_permission != permission):
        raise ValueError('Every confirmation must exactly match the site, tenant, subject and permission')
    source = Path(database).expanduser().absolute()
    backup = backup_database(source, backup_to)
    with closing(_readonly(Path(backup['destination']))) as restored:
        snapshot = _snapshot(restored, site_id, tenant_id, subject_id, permission)
    if snapshot[2] != plan['site_permissions_before']:
        raise RuntimeError('Permission count changed since preview; no revocation made')
    with closing(sqlite3.connect(source, timeout=10)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            try:
                current = _snapshot(db, site_id, tenant_id, subject_id, permission)
            except ValueError as exc:
                raise RuntimeError('Ownership or permission changed since backup; no revocation made') from exc
            if current != snapshot:
                raise RuntimeError('Ownership or permission changed since backup; no revocation made')
            deleted = db.execute('DELETE FROM site_permissions WHERE site_id=? AND '
                                 'subject_id=? AND permission=?',
                                 (site_id, subject_id, permission))
            if deleted.rowcount != 1 or has_site_permission(
                    db, site_id=site_id, trusted_tenant_id=tenant_id,
                    trusted_subject_id=subject_id, permission=permission):
                raise RuntimeError('Revocation verification failed; no change committed')
            count = db.execute('SELECT COUNT(*) FROM site_permissions WHERE site_id=?',
                               (site_id,)).fetchone()[0]
            if count != snapshot[2] - 1 or db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Unexpected permission or foreign-key change; no revocation committed')
            db.commit()
        except Exception:
            db.rollback()
            raise
    if inspect_schema(source)['status'] != 'ready':
        raise RuntimeError('Post-revocation audit failed; preserve backup for independent review')
    return {**plan, 'mode': 'applied', 'site_permissions_after': snapshot[2] - 1,
            'verified_backup': backup,
            'no_token_or_session_revocation_performed': True}


def main() -> None:
    parser = argparse.ArgumentParser(description='Preview or revoke one offline Analytics site grant')
    parser.add_argument('--database', required=True)
    parser.add_argument('--site-id', required=True)
    parser.add_argument('--tenant-id', required=True)
    parser.add_argument('--subject-id', required=True)
    parser.add_argument('--permission', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-to')
    parser.add_argument('--confirm-site-id')
    parser.add_argument('--confirm-tenant-id')
    parser.add_argument('--confirm-subject-id')
    parser.add_argument('--confirm-permission')
    options = parser.parse_args()
    confirmations = [options.confirm_site_id, options.confirm_tenant_id,
                     options.confirm_subject_id, options.confirm_permission]
    if options.apply and (not options.backup_to or not all(confirmations)):
        parser.error('--apply requires --backup-to and all four --confirm-* fields')
    if not options.apply and (options.backup_to or any(confirmations)):
        parser.error('--backup-to and --confirm-* require --apply')
    try:
        result = (apply_permission_revocation(
            options.database, options.site_id, options.tenant_id, options.subject_id,
            options.permission, options.backup_to, *confirmations)
            if options.apply else preview_permission_revocation(
                options.database, options.site_id, options.tenant_id,
                options.subject_id, options.permission))
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
