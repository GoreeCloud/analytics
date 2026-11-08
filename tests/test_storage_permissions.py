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
