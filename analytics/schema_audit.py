"""Non-mutating SQLite schema and integrity preflight for GoreeCloud Analytics.

This is NOT a migration runner. Use a separate validated offline snapshot
when the source database is active; concurrent writes affect live readback.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

# The actual v0.1.2 development layout; earlier builds wrote user_version=0.
REQUIRED_COLUMNS = {
    "sites": {"id", "name", "domains", "created_at"},
    "site_domains": {"site_id", "domain", "challenge", "verified_at"},
    "sessions": {"id", "site_id", "visitor_hash", "first_seen", "last_seen", "event_count"},
    "events": {"id", "site_id", "session_id", "visitor_hash", "ts", "kind", "path",
               "hostname", "referrer", "name", "properties", "ua_family",
               "utm_source", "utm_medium", "utm_campaign"},
    "goals": {"id", "site_id", "name", "kind", "target", "created_at"},
}


def inspect_schema(path: str | Path) -> dict:
    """Read an existing database without creating it or changing its schema."""
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
                # Table names are hardcoded above, never request-derived.
                actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                absent = sorted(columns - actual)
                if absent:
                    missing_columns[table] = absent
            invalid_fk = db.execute("PRAGMA foreign_key_check").fetchmany(1)
            ready = not missing and not missing_columns and not invalid_fk
            return {
                "database": str(target),
                "user_version": version,
                "status": "current-structure-unversioned" if ready and version == 0
                          else "review-required",
                "missing_tables": missing,
                "missing_columns": missing_columns,
                "foreign_key_violations_detected": bool(invalid_fk),
                "schema_migration_performed": False,
            }
    except sqlite3.DatabaseError as exc:
        raise ValueError("SQLite inspection failed") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Analytics SQLite schema preflight")
    parser.add_argument("--database", required=True, help="Existing SQLite database or verified backup")
    args = parser.parse_args()
    try:
        result = inspect_schema(args.database)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "current-structure-unversioned":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
