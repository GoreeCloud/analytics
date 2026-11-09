"""Retention needs an exact, verified recovery snapshot before deleting records."""
import sqlite3

import pytest

from analytics import maintenance
from analytics.backup import verify_backup
from analytics.maintenance import apply_retention, retention_report
from analytics.storage import Storage


def example(tmp_path):
    path = tmp_path / "analytics.sqlite3"
    store = Storage(str(path))
    with store.connect() as db:
        db.execute("INSERT INTO sites VALUES(?,?,?,?)",
                   ("alpha", "Alpha", '["a.example.com"]', "2026-01-01"))
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                   ("visit-a", "alpha", "anon", "2025-01-01", "2025-01-01", 1))
        db.execute("INSERT INTO events(id,site_id,session_id,visitor_hash,ts,kind,"
                   "path,hostname) VALUES(?,?,?,?,?,?,?,?)",
                   ("event-a", "alpha", "visit-a", "anon", "2025-01-01",
                    "pageview", "/original", "a.example.com"))
    return store


def test_direct_retention_mutation_without_verified_backup_is_rejected(tmp_path):
    store = example(tmp_path)
    with pytest.raises(ValueError, match="verified backup"):
        retention_report(store, 90, apply=True)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_same_count_intervening_change_fails_closed_and_keeps_backup(tmp_path, monkeypatch):
    store = example(tmp_path)
    original = maintenance.backup_database
    def change_after_backup(*args):
        evidence = original(*args)
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE events SET path=? WHERE id=?", ("/changed", "event-a"))
        return evidence
    monkeypatch.setattr(maintenance, "backup_database", change_after_backup)
    backup = tmp_path / "retention.sqlite3"
    with pytest.raises(RuntimeError, match="contents changed since retention backup"):
        apply_retention(store, 90, backup)
    assert verify_backup(backup)["events"] == 1
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT path FROM events").fetchone()[0] == "/original"
    with store.connect() as db:
        assert db.execute("SELECT path FROM events").fetchone()[0] == "/changed"
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_retention_with_exact_snapshot_prunes_expired_events(tmp_path):
    store = example(tmp_path)
    backup = tmp_path / "retention.sqlite3"
    result = apply_retention(store, 90, backup)
    assert result["mode"] == "applied" and result["events"] == 1
    assert verify_backup(backup)["events"] == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
