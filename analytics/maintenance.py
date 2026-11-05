"""Explicit, offline retention maintenance for the single-node SQLite alpha.

No destructive operation occurs unless --apply is provided. Run a verified
backup before removing any historical analytics data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .storage import Storage
from .backup import backup_database


def retention_report(storage: Storage, days: int, *, apply: bool = False,
                     now: datetime | None = None) -> dict:
    """Report or prune events older than days, plus orphaned expired visits.

    This is an explicit offline operation, NOT a background retention worker.
    """
    if not 1 <= days <= 3650:
        raise ValueError("Retention days must be between 1 and 3650")
    when = now or datetime.now(timezone.utc)
    cutoff = (when.astimezone(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
    with storage.connect() as db:
        # Readers and writers cannot interleave with a purge between preview
        # and deletion. No data is deleted by default.
        if apply:
            db.execute("BEGIN IMMEDIATE")
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
        evidence = backup_database(args.database, args.backup_to) if args.apply else None
        report = retention_report(Storage(args.database), args.days, apply=args.apply)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    print(json.dumps({**report, **({"backup": evidence} if evidence else {})}, indent=2))


if __name__ == "__main__":
    main()
