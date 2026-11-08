"""SQLite persistence for the single-node MVP; migration to Postgres is planned."""
import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path

from .schema_audit import REQUIRED_COLUMNS

SCHEMA_VERSION = 1
EXPECTED_TABLES = frozenset({"sites", "site_domains", "sessions", "events", "goals"})

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sites (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domains TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_domains (
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  challenge TEXT NOT NULL,
  verified_at TEXT,
  PRIMARY KEY (site_id, domain)
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  visitor_hash TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  event_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sessions_recent ON sessions(site_id, visitor_hash, last_seen);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  visitor_hash TEXT NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('pageview','event')),
  path TEXT NOT NULL,
  hostname TEXT NOT NULL,
  referrer TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  properties TEXT NOT NULL DEFAULT '{}',
  ua_family TEXT NOT NULL DEFAULT '',
  utm_source TEXT NOT NULL DEFAULT '',
  utm_medium TEXT NOT NULL DEFAULT '',
  utm_campaign TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_events_site_ts ON events(site_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_session ON events(session_id, ts);
CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('pageview','event')),
  target TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(site_id, name)
);
CREATE INDEX IF NOT EXISTS ix_goals_site ON goals(site_id);
"""


class Storage:
    def __init__(self, path: str):
        self.path = path
        created = path == ":memory:"
        if path != ":memory:":
            target = Path(path)
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if target.is_symlink():
                raise ValueError("Database path cannot be a symbolic link")
            if not target.exists():
                try:
                    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                except FileExistsError:
                    pass  # Another process won creation; it must finish setup first.
                else:
                    os.close(fd)
                    created = True
        with self.connect() as db:
            if created:
                db.executescript(SCHEMA)
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                return
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            valid = version == SCHEMA_VERSION and EXPECTED_TABLES.issubset(tables)
            if valid:
                for table, required in REQUIRED_COLUMNS.items():
                    columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                    if not required.issubset(columns):
                        valid = False
                        break
            if not valid:
                # Fail closed instead of silently modifying a live legacy DB.
                # Operators must take an offline verified backup and explicitly
                # run the narrow migration CLI before restarting the service.
                raise RuntimeError(
                    "Database schema is unversioned/incomplete or unsupported. "
                    "Stop the service; run python -m analytics.migrate with "
                    "--database, --backup-to and --apply after an offline review."
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
