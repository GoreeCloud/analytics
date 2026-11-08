"""Non-mutating SQLite schema and integrity preflight for GoreeCloud Analytics.

This is NOT a migration runner. Use a separate validated snapshot for offline
inspection if the source database is active, since concurrent writes can affect
point-in-time results and SQLite read-only WAL clients may use a -shm file.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

# This list describes the actual v0.1.2 development schema. No schema version
# was assigned by earlier builds; PRAGMA user_version=0 is expected for them.
REQUIRED_COLUMNS = {
    "sites": {"id", "name", "domains", "created_at"},
    "site_domains": {"site_id", "domain", "challenge", "verified_at"},
    "sessions": {"id", "site_id", "visitor_hash", "first_seen", "last_seen", "event_count"},
    "events": {"id", "site_id", "session_id", "visitor_hash", "ts", "kind", "path",
               "hostname", "referrer", "name", "properties", "ua_family", "utm_source",
               "utm_medium", "utm_campaign"},
    "goals": {"id", "site_id", "name", "kind", "target", "created_at"},
}


def inspect_schema(path: str | Path) -> dict:
    """Read a database without creating it or changing its schema or data."""
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ValueError("Database must be an existing regular file, not a symlink")
    try:
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            db.execute("PRAGMA query_only=ON")
            integrity = db.execute("PRAGMA quick_check(1)").fetchone()[0]
            if integrity != "ok":
                raise ValueError("SQLite quick integrity check failed")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            missing = sorted(set(REQUIRED_COLUMNS) - tables)
            missing_columns = {}
            for table, columns in REQUIRED_COLUMNS.items():
                if table not in tables:
                    continue
                # Table names are hardcoded above and never request-derived.
                actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                absent = sorted(columns - actual)
                if absent:
                    missing_columns[table] = absent
            invalid_fk = db.execute("PRAGMA foreign_key_check").fetchmany(1)
            # No schema version is written or inferred. Older Analytics schemas
            # are detected but are NEVER silently repaired by this audit.
            ready = not missing and not missing_columns and not invalid_fk
            can_migrate = (version == 0 and not missing_columns and not invalid_fk
                           and (not missing or missing == ["site_domains"]))
            status = ("ready" if ready and version == 1 else
                      "migration-required" if can_migrate else "review-required")
            return {
                "database": str(target),
                "user_version": version,
                "status": status,
                "missing_tables": missing,
                "missing_columns": missing_columns,
                "foreign_key_violations_detected": bool(invalid_fk),
                "schema_migration_performed": False,
            }
    except sqlite3.DatabaseError as exc:
        raise ValueError("SQLite inspection failed") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only GoreeCloud Analytics SQLite schema preflight")
    parser.add_argument("--database", required=True, help="Existing SQLite database or verified backup")
    args = parser.parse_args()
    try:
        result = inspect_schema(args.database)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "ready":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
