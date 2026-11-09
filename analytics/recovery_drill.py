"""Non-destructive, offline restore drill for a private Analytics v2 backup.

No network, database migrations, live database writes, or automatic switches.
A disposable restored copy is compared to the source backup by schema and the
actual contents of all seven current Analytics tables, then removed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from .backup import restore_database, verify_backup
from .schema_audit import inspect_schema

TABLES = ("sites", "site_domains", "sessions", "events", "goals",
          "site_owners", "site_permissions")


def _private(path: Path, description: str, *, directory: bool) -> None:
    if path.is_symlink():
        raise ValueError(f"{description} cannot be a symbolic link")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"{description} must be an existing regular {'directory' if directory else 'file'}")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"{description} must have owner-only permissions")


def _typed(value):
    # The type tag prevents collisions between binary data and text, or
    # numbers and strings that happen to have identical printed values.
    if value is None:
        return ["null", None]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if type(value) is str:
        return ["text", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        return ["real", repr(value)]
    raise ValueError("Unexpected SQLite value type")


def _fingerprint(path: Path) -> tuple:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Recovery candidate has foreign key violations")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        schema = hashlib.sha256()
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            schema.update(json.dumps([_typed(value) for value in row],
                                     separators=(",", ":"), ensure_ascii=True).encode() + b"\n")
        tables = []
        for table in TABLES:
            checksum = hashlib.sha256()
            count = 0
            # Identifiers are fixed constants, never user-supplied SQL.
            for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                checksum.update(json.dumps([_typed(value) for value in row],
                                           separators=(",", ":"), ensure_ascii=True).encode() + b"\n")
                count += 1
            tables.append((table, count, checksum.hexdigest()))
    return (version, schema.hexdigest(), tuple(tables))


def drill_backup(backup: str | Path, scratch_dir: str | Path) -> dict:
    """Prove a vetted backup restores into a disposable private destination."""
    source = Path(backup).expanduser().absolute()
    scratch = Path(scratch_dir).expanduser().absolute()
    _private(source, "Backup", directory=False)
    _private(scratch, "Scratch directory", directory=True)
    if source.parent == scratch:
        # We never overwrite the source, but require a separately designated
        # scratch folder to avoid polluting the backup inventory accidentally.
        raise ValueError("Scratch directory must differ from the backup directory")
    verify_backup(source)
    report = inspect_schema(source)
    if report["status"] != "ready" or report["user_version"] != 2:
        raise ValueError("Recovery drill requires a structurally ready SQLite v2 backup")
    expected = _fingerprint(source)
    with tempfile.TemporaryDirectory(prefix=".goreecloud-restore-drill-", dir=scratch) as work:
        restored = Path(work) / "restored.sqlite3"
        restore_database(source, restored)
        check = inspect_schema(restored)
        if check["status"] != "ready" or check["user_version"] != 2:
            raise ValueError("Restored SQLite v2 schema verification failed")
        actual = _fingerprint(restored)
        if expected != actual:
            raise ValueError("Restored schema or table data differs from backup")
    return {
        "status": "passed", "schema_version": 2,
        "tables_compared": list(TABLES),
        "row_counts": {table: count for table, count, _ in expected[2]},
        "restored_to_disposable_private_directory": True,
        "source_backup_unchanged_by_tool": True,
        "no_live_database_restore_performed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline non-destructive Analytics SQLite v2 restore drill")
    parser.add_argument("--backup", required=True, help="Verified private SQLite v2 backup file")
    parser.add_argument("--scratch-dir", required=True, help="Existing owner-only scratch directory")
    args = parser.parse_args()
    try:
        result = drill_backup(args.backup, args.scratch_dir)
    except (OSError, sqlite3.DatabaseError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
