"""Sensitive SQLite backups require a protected, non-symlink destination directory."""
import os
import stat
import sqlite3
import pytest
from analytics.storage import Storage
from analytics.backup import backup_database, verify_backup


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes required")
@pytest.mark.parametrize("unsafe_mode", [0o755, 0o750, 0o707])
def test_backup_refuses_group_or_other_accessible_destination(tmp_path, unsafe_mode):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    target_dir = tmp_path / "backup-destination"
    target_dir.mkdir(mode=0o700)
    target_dir.chmod(unsafe_mode)
    output = target_dir / "snapshot.sqlite3"
    with pytest.raises(PermissionError, match="owner-only"):
        backup_database(source, output)
    assert not output.exists()
    assert list(target_dir.iterdir()) == []


def test_backup_refuses_symlink_destination_and_keeps_live_data(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    private = tmp_path / "private-backups"
    private.mkdir(mode=0o700)
    destination = tmp_path / "backup-link"
    try:
        destination.symlink_to(private, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symbolic link"):
        backup_database(source, destination / "snapshot.sqlite3")
    assert not list(private.iterdir())
    assert source.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes required")
def test_backup_accepts_private_folder_and_keeps_snapshot_owner_only(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    private = tmp_path / "private-backups"
    private.mkdir(mode=0o700)
    output = private / "snapshot.sqlite3"
    result = backup_database(source, output)
    assert result["status"] == "verified"
    assert verify_backup(output)["status"] == "verified"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(private.stat().st_mode) == 0o700


def test_backup_rejects_foreign_key_orphans_even_when_sqlite_integrity_is_ok(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("INSERT INTO site_permissions(site_id,subject_id,permission,granted_at) "
                   "VALUES(?,?,?,?)", ("nonexistent-site", "person", "analytics:read", "2026-11-08"))
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is not None
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    dest = private / "bad.sqlite3"
    with pytest.raises(ValueError, match="foreign-key"):
        backup_database(source, dest)
    assert not dest.exists() and list(private.iterdir()) == []


def test_backup_rejects_unknown_user_version_and_unsupported_layout(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA user_version=987")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    dest = private / "unsupported.sqlite3"
    with pytest.raises(ValueError, match="unrecognized"):
        backup_database(source, dest)
    assert not dest.exists()
    with pytest.raises(ValueError, match="unrecognized"):
        verify_backup(source)


def test_backup_reports_valid_schema_version_and_status(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    dest = private / "snapshot.sqlite3"
    evidence = backup_database(source, dest)
    assert evidence["status"] == "verified"
    assert evidence["user_version"] == 2
    assert evidence["schema_status"] == "ready"
    assert verify_backup(dest)["user_version"] == 2
