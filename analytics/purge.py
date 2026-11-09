"""Manual, backup-gated deletion of an entire Analytics site and its records.

Development-only CLI. Never runs automatically or against a live service by
itself. It does not implement per-visitor data-subject identification/deletion.
"""
from __future__ import annotations

import argparse
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .backup import backup_database
from .schema_audit import inspect_schema

TABLES = ("sites", "site_domains", "sessions", "events", "goals",
          "site_owners", "site_permissions")


def _ready_database(database: str | Path) -> Path:
    result = inspect_schema(database)
    if result["status"] != "ready":
        raise ValueError("Database must pass the current schema audit before deletion")
    return Path(database).expanduser().absolute()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _site_counts(db: sqlite3.Connection, site_id: str) -> dict[str, int] | None:
    if db.execute("SELECT 1 FROM sites WHERE id=?", (site_id,)).fetchone() is None:
        return None
    return {table: db.execute(f"SELECT COUNT(*) FROM {table} WHERE "
                              f"{'id' if table == 'sites' else 'site_id'}=?",
                              (site_id,)).fetchone()[0] for table in TABLES}


def _all_counts(db: sqlite3.Connection) -> dict[str, int]:
    return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES}


def _fingerprint(db: sqlite3.Connection, *, exclude_site: str | None = None) -> str:
    """Hash exact SQLite row contents, not only counts, without materializing rows.

    Called on a verified backup and again under an active SQLite writer lock.
    Table/column names come exclusively from the static TABLES allowlist.
    """
    digest = hashlib.sha256()
    for table in TABLES:
        digest.update(("table:" + table + "\n").encode())
        key = "id" if table == "sites" else "site_id"
        where = f" WHERE {key} != ?" if exclude_site is not None else ""
        args = (exclude_site,) if exclude_site is not None else ()
        for row in db.execute(f"SELECT * FROM {table}{where} ORDER BY rowid", args):
            typed = []
            for value in row:
                if value is None:
                    typed.append(["null", None])
                elif isinstance(value, bytes):
                    typed.append(["blob", value.hex()])
                elif type(value) is int:
                    typed.append(["integer", value])
                elif type(value) is float:
                    typed.append(["real", repr(value)])
                elif type(value) is str:
                    typed.append(["text", value])
                else:
                    raise ValueError("Unsupported SQLite value in deletion preflight")
            digest.update(json.dumps(typed, separators=(",", ":"), ensure_ascii=True).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def preview_purge(database: str | Path, site_id: str) -> dict:
    """Read-only preview: no schema change or backup creation."""
    if not isinstance(site_id, str) or not (1 <= len(site_id) <= 100):
        raise ValueError("A valid existing site ID is required")
    path = _ready_database(database)
    with closing(_connect_readonly(path)) as db:
        counts = _site_counts(db, site_id)
        if counts is None:
            raise ValueError("Unknown site ID; no records were deleted")
    return {"mode": "preview", "site_id": site_id, "deletion_counts": counts,
            "requires_offline_service": True, "backup_required": True}


def apply_purge(database: str | Path, site_id: str, backup_to: str | Path,
                confirmation: str) -> dict:
    """Delete one site atomically only after an exclusive verified backup.

    Operators must stop other SQLite writers. Exact content hashes under the
    writer lock detect same-count mutations, but cannot prove services stopped.
    """
    plan = preview_purge(database, site_id)
    if confirmation != site_id:
        raise ValueError("Deletion confirmation must exactly match the site ID")
    path = Path(database).expanduser().absolute()
    evidence = backup_database(path, backup_to)
    backup_path = Path(evidence["destination"])
    with closing(_connect_readonly(backup_path)) as snapshot:
        snapshot_site = _site_counts(snapshot, site_id)
        snapshot_totals = _all_counts(snapshot)
        snapshot_fingerprint = _fingerprint(snapshot)
        unaffected_fingerprint = _fingerprint(snapshot, exclude_site=site_id)
    if snapshot_site != plan["deletion_counts"]:
        raise RuntimeError("Site changed during backup; no data deleted")
    with closing(sqlite3.connect(path, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            # Fail closed on interleaved writes since backup; retain the backup.
            if (_site_counts(db, site_id) != snapshot_site or
                    _all_counts(db) != snapshot_totals or
                    _fingerprint(db) != snapshot_fingerprint):
                raise RuntimeError("Database contents changed since backup; no data deleted")
            deleted = db.execute("DELETE FROM sites WHERE id=?", (site_id,))
            if deleted.rowcount != 1 or _site_counts(db, site_id) is not None:
                raise RuntimeError("Site deletion could not be verified")
            remaining = _all_counts(db)
            for table in TABLES:
                if remaining[table] != snapshot_totals[table] - snapshot_site[table]:
                    raise RuntimeError("Site-dependent records were not fully deleted")
            if _fingerprint(db, exclude_site=site_id) != unaffected_fingerprint:
                raise RuntimeError("Unrelated site records changed; deletion rolled back")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("Deletion would violate database foreign keys")
            db.commit()
        except Exception:
            db.rollback()
            raise
    if inspect_schema(path)["status"] != "ready":
        raise RuntimeError("Post-deletion schema audit failed; preserve backup")
    return {"mode": "applied", "site_id": site_id,
            "deleted": snapshot_site, "verified_backup": evidence,
            "does_not_identify_individual_visitors": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or explicitly purge a GoreeCloud Analytics site")
    parser.add_argument("--database", required=True, help="Existing stopped Analytics SQLite DB")
    parser.add_argument("--site-id", required=True, help="Site ID to purge")
    parser.add_argument("--apply", action="store_true", help="Delete after an exclusive verified backup")
    parser.add_argument("--backup-to", help="New backup path, required with --apply")
    parser.add_argument("--confirm-site-id", help="Re-enter the exact ID to authorize deletion")
    opts = parser.parse_args()
    if opts.apply and (not opts.backup_to or not opts.confirm_site_id):
        parser.error("--apply requires --backup-to and --confirm-site-id")
    if not opts.apply and (opts.backup_to or opts.confirm_site_id):
        parser.error("--backup-to and --confirm-site-id require --apply")
    try:
        result = (apply_purge(opts.database, opts.site_id, opts.backup_to,
                              opts.confirm_site_id) if opts.apply else
                  preview_purge(opts.database, opts.site_id))
    except (ValueError, RuntimeError, OSError, sqlite3.DatabaseError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()