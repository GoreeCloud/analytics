"""Explicit and backup-gated migration from known unversioned Analytics schemas.

Only the v0 to v1 SQLite schema step is supported. This is an offline
maintenance command, never a startup auto-upgrade or background service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sqlite3
from contextlib import closing

from .backup import backup_database
from .privacy import normalize_domain
from .schema_audit import inspect_schema
from .verification import txt_record_name

TARGET_VERSION = 1
SITE_DOMAINS_DDL = """
CREATE TABLE IF NOT EXISTS site_domains (
    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    challenge TEXT NOT NULL,
    verified_at TEXT,
    PRIMARY KEY (site_id, domain)
)
"""


def preview_migration(database: str | Path) -> dict:
    """Inspect without touching a database; only recognized v0 is upgradeable."""
    report = inspect_schema(database)
    if report["status"] == "ready":
        return {**report, "action": "none", "target_version": TARGET_VERSION}
    if report["status"] != "migration-required":
        raise ValueError("Unrecognized or inconsistent database schema; manual review required")
    with closing(sqlite3.connect(Path(database).expanduser().absolute().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        for (raw,) in db.execute("SELECT domains FROM sites"):
            try:
                domains = json.loads(raw)
                if not isinstance(domains, list) or not domains:
                    raise ValueError("No registered domains")
                for item in domains:
                    if not isinstance(item, str) or normalize_domain(item) != item:
                        raise ValueError("Unrecognized domain")
                    if len(item) + len(txt_record_name("")) > 253:
                        raise ValueError("DNS challenge name too long")
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid legacy domain registration; manual review required") from exc
    return {**report, "action": "apply-with-verified-backup",
            "target_version": TARGET_VERSION,
            "newly_created_proofs_will_be_pending": True}


def apply_migration(database: str | Path, backup_to: str | Path) -> dict:
    """Back up to exclusive path before one atomic v0 -> v1 transaction."""
    plan = preview_migration(database)
    if plan["action"] == "none":
        return {**plan, "mode": "already-current", "backup": None}
    backup = backup_database(database, backup_to)
    db_path = Path(database).expanduser().absolute()
    with closing(sqlite3.connect(db_path, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            # Recheck while holding the writer lock; do not apply to a changed DB.
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version != 0:
                raise ValueError("Database schema version changed during migration")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "site_domains" not in tables:
                db.execute(SITE_DOMAINS_DDL)
            # Existing proof rows are preserved; missing legacy hostnames
            # are inserted as pending, never assumed verified.
            for site_id, raw in db.execute("SELECT id, domains FROM sites"):
                domains = json.loads(raw)
                for domain in domains:
                    if normalize_domain(domain) != domain:
                        raise ValueError("Legacy domain normalization changed")
                    db.execute("INSERT OR IGNORE INTO site_domains(site_id,domain,challenge,verified_at) "
                               "VALUES(?,?,?,NULL)",
                               (site_id, domain, secrets.token_urlsafe(32)))
            db.execute(f"PRAGMA user_version={TARGET_VERSION}")
            db.commit()
        except Exception:
            db.rollback()
            raise
    result = inspect_schema(db_path)
    if result["status"] != "ready":
        raise RuntimeError("Post-migration integrity failed; preserve backup for recovery")
    return {**result, "mode": "applied", "backup": backup,
            "newly_created_proofs_are_pending": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit offline Analytics SQLite migration")
    parser.add_argument("--database", required=True, help="Existing single-node Analytics DB")
    parser.add_argument("--apply", action="store_true", help="Apply after creating and verifying a backup")
    parser.add_argument("--backup-to", help="New private backup destination; mandatory with --apply")
    args = parser.parse_args()
    if args.apply and not args.backup_to:
        parser.error("--apply requires --backup-to")
    if args.backup_to and not args.apply:
        parser.error("--backup-to is only permitted with --apply")
    try:
        response = (apply_migration(args.database, args.backup_to)
                    if args.apply else preview_migration(args.database))
    except (OSError, sqlite3.DatabaseError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(response, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
