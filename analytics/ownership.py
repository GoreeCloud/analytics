"""Pure site/subject permission lookup over operator-owned SQLite bindings.

SECURITY: Caller MUST supply tenant and subject from a separately authenticated
and cryptographically verified Identity token. This module authenticates nobody;
it is not called by the current legacy administrator API.
"""
from __future__ import annotations

import sqlite3

PERMISSIONS = frozenset({
    "analytics:read", "analytics:export", "analytics:manage", "analytics:admin",
    "analytics:delete",
})


def has_site_permission(
    db: sqlite3.Connection, *, site_id: str, trusted_tenant_id: str,
    trusted_subject_id: str, permission: str,
) -> bool:
    """Fail closed on absent owner, subject, exact action or malformed input.

    The tenant ID MUST be from a verified signed claim but MUST NOT be used to
    create the site ownership row. The subject MUST be an authenticated `sub`
    for the separately pinned Identity issuer/audience/authorized OAuth client.
    """
    if (type(site_id) is not str or not site_id or len(site_id) > 100 or
            type(trusted_tenant_id) is not str or not trusted_tenant_id or
            len(trusted_tenant_id) > 128 or
            type(trusted_subject_id) is not str or not trusted_subject_id or
            len(trusted_subject_id) > 255 or permission not in PERMISSIONS):
        return False
    try:
        row = db.execute(
            "SELECT 1 FROM site_owners o "
            "JOIN site_permissions p ON p.site_id=o.site_id "
            "WHERE o.site_id=? AND o.tenant_id=? "
            "AND p.subject_id=? AND p.permission=? LIMIT 1",
            (site_id, trusted_tenant_id, trusted_subject_id, permission),
        ).fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None
