"""Existing SQLite storage may not expose visitor data via file mode."""
import os
import stat

import pytest
from analytics.storage import Storage


@pytest.mark.skipif(os.name != 'posix', reason='POSIX file mode required')
def test_existing_database_with_group_or_world_access_fails_closed(tmp_path):
    target = tmp_path / 'analytics.sqlite3'
    Storage(str(target))
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    for unsafe in (0o640, 0o604, 0o644, 0o666):
        target.chmod(unsafe)
        with pytest.raises(PermissionError, match='owner-only'):
            Storage(str(target))
    target.chmod(0o600)
    Storage(str(target))  # repair does not require dropping data


def test_nonregular_database_targets_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='regular file'):
        Storage(str(tmp_path))
    database = tmp_path / 'db.sqlite3'
    Storage(str(database))
    link = tmp_path / 'link.sqlite3'
    try:
        link.symlink_to(database)
    except (NotImplementedError, OSError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='symbolic link'):
        Storage(str(link))


@pytest.mark.skipif(os.name != 'posix', reason='POSIX file mode required')
@pytest.mark.parametrize('suffix', ['-wal','-shm','-journal'])
def test_world_readable_sqlite_sidecar_is_rejected_before_open(tmp_path, suffix):
    database = tmp_path / 'analytics.sqlite3'
    Storage(str(database))
    sibling = tmp_path / ('analytics.sqlite3' + suffix)
    sibling.write_bytes(b'not live data')
    sibling.chmod(0o644)
    with pytest.raises(PermissionError, match='SQLite sidecar'):
        Storage(str(database))
    sibling.unlink()
    Storage(str(database))


def test_sqlite_sidecar_symlinks_and_nonregular_files_rejected(tmp_path):
    database = tmp_path / 'analytics.sqlite3'
    Storage(str(database))
    sibling = tmp_path / 'analytics.sqlite3-wal'
    sibling.mkdir()
    with pytest.raises(ValueError, match='sidecar must be a regular file'):
        Storage(str(database))
    sibling.rmdir()
    try:
        sibling.symlink_to(database)
    except (NotImplementedError, OSError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='sidecar cannot be a symbolic link'):
        Storage(str(database))
