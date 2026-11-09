"""Explicit, offline retention maintenance for the single-node SQLite alpha.

No destructive operation occurs unless --apply is provided. Run a verified
backup before removing any historical analytics data.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .storage import Storage
from .backup import backup_database
from .purge import _fingerprint


def retention_report(storage: Storage, days: int, *, apply: bool = False,
                     now: datetime | None = None,
                     expected_backup_fingerprint: str | None = None) -> dict:
    """Report or prune events older than days, plus orphaned expired visits.

    This is an explicit offline operation, NOT a background retention worker.
    """
    if not 1 <= days <= 3650:
        raise ValueError("Retention days must be between 1 and 3650")
    if apply and not expected_backup_fingerprint:
        raise ValueError("Apply requires a verified backup content fingerprint")
    when = now or datetime.now(timezone.utc)
    cutoff = (when.astimezone(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
    with storage.connect() as db:
        # Readers and writers cannot interleave with a purge between preview
        # and deletion. No data is deleted by default.
        if apply:
            db.execute("BEGIN IMMEDIATE")
            # Recheck exact contents after the backup, under the writer lock.
            # A same-count edit to retained or prunable events must not be
            # silently discarded with an out-of-date recovery snapshot.
            if _fingerprint(db) != expected_backup_fingerprint:
                raise RuntimeError("Database contents changed since retention backup; no pruning done")
        before = db.execute("SELECT COUNT(*) FROM events WHERE ts < ?", (cutoff,)).fetchone()[0]
        sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE last_seen < ? "
                              "AND NOT EXISTS (SELECT 1 FROM events WHERE events.session_id=sessions.id "
                              "AND events.ts>=?)", (cutoff, cutoff)).fetchone()[0]
        if apply:
            db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            # Preserve sessions that still contain in-retention events.
            db.execute("DELETE FROM sessions WHERE last_seen < ? "
                       "AND NOT EXISTS (SELECT 1 FROM events WHERE events.session_id=sessions.id)",
                       (cutoff,))
    return {"mode": "applied" if apply else "preview", "cutoff_utc": cutoff,
            "events": before, "expired_sessions": sessions}


def apply_retention(storage: Storage, days: int, backup_to: str | Path,
                    *, now: datetime | None = None) -> dict:
    """Offline retention with exact-content backup precondition.

    Callers must stop concurrent writers. A writer-lock content check also
    rejects any intervening changes between snapshot and destructive prune.
    """
    if not 1 <= days <= 3650:
        raise ValueError("Retention days must be between 1 and 3650")
    evidence = backup_database(storage.path, backup_to)
    backup_path = Path(evidence["destination"]).expanduser().absolute()
    with closing(sqlite3.connect(backup_path.as_uri() + "?mode=ro",
                                 uri=True, timeout=10)) as snapshot:
        snapshot.execute("PRAGMA query_only=ON")
        expected = _fingerprint(snapshot)
    result = retention_report(storage, days, apply=True, now=now,
                              expected_backup_fingerprint=expected)
    return {**result, "backup": evidence}


def main() -> None:
    p = argparse.ArgumentParser(description="Preview or apply GoreeCloud Analytics retention.")
    p.add_argument("--database", required=True, help="Path to the single-node SQLite database")
    p.add_argument("--days", type=int, default=90, help="Retention period in days (default: 90)")
    p.add_argument("--apply", action="store_true", help="Permanently delete expired rows (requires --backup-to)")
    p.add_argument("--backup-to", help="New, verified SQLite backup written before any pruning")
    args = p.parse_args()
    if not 1 <= args.days <= 3650:
        p.error("--days must be between 1 and 3650")
    # Storage bootstraps new databases for normal app starts. Retention must
    # refuse typos instead of silently creating an empty database to prune.
    if args.database == ":memory:" or not Path(args.database).is_file():
        p.error("--database must name an existing SQLite database file")
    if args.apply and not args.backup_to:
        p.error("--apply requires --backup-to for a verified pre-prune snapshot")
    if args.backup_to and not args.apply:
        p.error("--backup-to is only used with --apply")
    try:
        storage = Storage(args.database)
        report = (apply_retention(storage, args.days, args.backup_to) if args.apply
                  else retention_report(storage, args.days))
    except (ValueError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        p.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
