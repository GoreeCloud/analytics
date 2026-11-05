"""Consistent, verified SQLite backups for the early single-node Analytics service.

Backups are created with SQLite's online backup API instead of copying a live
WAL database. Destination creation is exclusive: existing files are never
replaced. A backup contains visitor analytics; store it in private storage.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import sqlite3
import tempfile
from pathlib import Path

REQUIRED_TABLES = frozenset({"sites", "sessions", "events", "goals"})


def _existing_db(path: str | Path) -> Path:
    db = Path(path).expanduser().absolute()
    if db.is_symlink() or not db.is_file():
        raise ValueError("Database must be an existing regular SQLite file, not a symlink")
    return db


def _readonly(path: Path) -> sqlite3.Connection:
    # URI read-only mode means misspelled paths cannot create empty databases.
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=20)


def verify_backup(path: str | Path) -> dict:
    """Verify SQLite integrity and expected Analytics schema without writes."""
    db_file = _existing_db(path)
    try:
        with closing(_readonly(db_file)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise ValueError("SQLite integrity check failed")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not REQUIRED_TABLES.issubset(tables):
                raise ValueError("Database does not contain the Analytics schema")
            return {
                "status": "verified",
                "sites": db.execute("SELECT COUNT(*) FROM sites").fetchone()[0],
                "sessions": db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "goals": db.execute("SELECT COUNT(*) FROM goals").fetchone()[0],
            }
    except sqlite3.DatabaseError as exc:
        raise ValueError("SQLite backup validation failed") from exc


def backup_database(source: str | Path, destination: str | Path) -> dict:
    """Make a transactionally consistent SQLite snapshot, validate, publish once.

    Source can be open for writes. The target is a new file created exclusively,
    never overwritten. A failed verification leaves no target or temp snapshot.
    """
    src = _existing_db(source)
    target = Path(destination).expanduser().absolute()
    if src == target or target.exists() or target.is_symlink():
        raise ValueError("Backup destination must be a new, distinct file")
    # Require an operator-chosen existing private directory to avoid creating a
    # world-readable backup tree in an accidental location.
    if not target.parent.is_dir():
        raise ValueError("Backup destination directory must already exist")
    handle, temp_name = tempfile.mkstemp(prefix=".goreecloud-backup-", suffix=".sqlite3",
                                         dir=str(target.parent))
    os.close(handle)  # mkstemp creates mode 0600, including under a liberal umask.
    temp = Path(temp_name)
    try:
        with closing(_readonly(src)) as source_db, closing(sqlite3.connect(temp)) as backup_db:
            source_db.backup(backup_db, pages=128, sleep=0.05)
        result = verify_backup(temp)
        with open(temp, "rb") as snapshot:
            os.fsync(snapshot.fileno())
        # link() is an exclusive, atomic new-name creation. Unlike replace() it
        # cannot destroy an existing backup if a concurrent process wins a race.
        os.link(temp, target)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass  # Not all filesystems allow fsync on directories.
        return {"destination": str(target), **result}
    finally:
        temp.unlink(missing_ok=True)


def restore_database(backup: str | Path, destination: str | Path) -> dict:
    """Restore a verified snapshot to a NEW database path (never in place).

    A running application must be stopped and deliberately configured to use
    the restored path after the owner has reviewed its contents. Existing live
    databases can never be overwritten through this recovery command.
    """
    verify_backup(backup)
    return {"action": "restore", **backup_database(backup, destination)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a GoreeCloud Analytics SQLite backup")
    parser.add_argument("--database", help="Existing Analytics database to back up")
    parser.add_argument("--output", help="New backup path within an existing private directory")
    parser.add_argument("--verify-only", metavar="PATH", help="Verify an existing backup without modifying it")
    parser.add_argument("--restore-from", metavar="PATH", help="Restore a verified snapshot to a new --output path")
    options = parser.parse_args()
    if options.verify_only:
        if options.database or options.output or options.restore_from:
            parser.error("--verify-only cannot be combined with other operations")
        action = lambda: verify_backup(options.verify_only)
    elif options.restore_from and options.output and not options.database:
        action = lambda: restore_database(options.restore_from, options.output)
    elif options.database and options.output and not options.restore_from:
        action = lambda: backup_database(options.database, options.output)
    else:
        parser.error("Provide --database and --output, --restore-from and --output, or --verify-only")
    try:
        print(json.dumps(action(), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
