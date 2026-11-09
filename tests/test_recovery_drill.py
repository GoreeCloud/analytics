"""Disposable backup restoration must preserve all current Analytics data."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from analytics.backup import backup_database
from analytics.recovery_drill import drill_backup
from analytics.storage import Storage


def fixture(tmp_path):
    original = tmp_path / "original.sqlite3"
    Storage(str(original))
    with sqlite3.connect(original) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO sites VALUES(?,?,?,?)",
                   ("site-a", "Test", json.dumps(["example.com"]), "2026-11-08"))
        db.execute("INSERT INTO site_domains VALUES(?,?,?,?)",
                   ("site-a", "example.com", "challenge", "2026-11-08"))
        db.execute("INSERT INTO site_owners VALUES(?,?,?,?)",
                   ("site-a", "tenant-a", "2026-11-08", "offline-operator"))
        db.execute("INSERT INTO site_permissions VALUES(?,?,?,?)",
                   ("site-a", "subject-a", "analytics:read", "2026-11-08"))
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                   ("visit-a", "site-a", "hash", "2026-11-08", "2026-11-08", 1))
        db.execute("INSERT INTO events(id,site_id,session_id,visitor_hash,ts,kind,"
                   "path,hostname) VALUES(?,?,?,?,?,?,?,?)",
                   ("event-a", "site-a", "visit-a", "hash", "2026-11-08", "pageview",
                    "/hello", "example.com"))
        db.execute("INSERT INTO goals VALUES(?,?,?,?,?,?)",
                   ("goal-a", "site-a", "Signup", "event", "signup", "2026-11-08"))
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    backup = backups / "backup.sqlite3"
    backup_database(original, backup)
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    return original, backup, scratch


def test_restore_drill_preserves_all_v2_tables_and_cleans_up(tmp_path):
    original, backup, scratch = fixture(tmp_path)
    before = backup.read_bytes()
    report = drill_backup(backup, scratch)
    assert report["status"] == "passed"
    assert report["schema_version"] == 2
    assert len(report["tables_compared"]) == 7
    assert report["row_counts"]["events"] == 1
    assert report["row_counts"]["site_permissions"] == 1
    assert list(scratch.iterdir()) == []
    assert backup.read_bytes() == before
    with sqlite3.connect(original) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode enforcement")
def test_insecure_backup_and_scratch_are_rejected_without_restore(tmp_path):
    _, backup, scratch = fixture(tmp_path)
    backup.chmod(0o644)
    with pytest.raises(PermissionError, match="Backup"):
        drill_backup(backup, scratch)
    backup.chmod(0o600)
    scratch.chmod(0o755)
    with pytest.raises(PermissionError, match="Scratch"):
        drill_backup(backup, scratch)
    assert not list(scratch.iterdir())


def test_corrupt_and_unknown_version_fail_without_disposable_artifacts(tmp_path):
    original, backup, scratch = fixture(tmp_path)
    backup.write_bytes(b"not a database")
    with pytest.raises(ValueError):
        drill_backup(backup, scratch)
    assert list(scratch.iterdir()) == []
    # Independently create an older v1 snapshot that must not appear ready.
    with sqlite3.connect(original) as db:
        db.execute("DROP TABLE site_permissions")
        db.execute("DROP TABLE site_owners")
        db.execute("PRAGMA user_version=1")
    alternate = backup.parent / "before-v2.sqlite3"
    backup_database(original, alternate)
    with pytest.raises(ValueError, match="SQLite v2"):
        drill_backup(alternate, scratch)
    assert list(scratch.iterdir()) == []


def test_nonexistent_scratch_and_links_fail_closed(tmp_path):
    _, backup, scratch = fixture(tmp_path)
    with pytest.raises(ValueError, match="Scratch"):
        drill_backup(backup, tmp_path / "nonexistent")
    link = tmp_path / "scratch-link"
    try:
        link.symlink_to(scratch, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symbolic link"):
        drill_backup(backup, link)


def test_cli_runs_the_same_disposable_restore_drill(tmp_path):
    _, backup, scratch = fixture(tmp_path)
    command = [sys.executable, "-m", "analytics.recovery_drill",
               "--backup", str(backup), "--scratch-dir", str(scratch)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["row_counts"]["site_owners"] == 1
    assert list(scratch.iterdir()) == []
