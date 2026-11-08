"""Site-scoped, backup-gated data deletion regression tests."""
import sqlite3
import subprocess
import sys

import pytest

from analytics.backup import verify_backup
from analytics.purge import preview_purge, apply_purge
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def populated(tmp_path):
    source = tmp_path / "analytics.sqlite3"
    Storage(str(source))
    with sqlite3.connect(source) as db:
        for site, domain in (("alpha", "a.example.com"), ("bravo", "b.example.com")):
            db.execute("INSERT INTO sites VALUES (?,?,?,?)", (site, site, '["' + domain + '"]', '2026-10-01'))
            db.execute("INSERT INTO site_domains VALUES (?,?,?,?)", (site, domain, '', '2026-11-01'))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                       (site + '-session', site, site + '-anon', '2026-11-01', '2026-11-01', 1))
            db.execute("INSERT INTO events(id,site_id,session_id,visitor_hash,ts,kind,path,hostname) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (site + '-event', site, site + '-session', site + '-anon',
                        '2026-11-01', 'pageview', '/' + site, domain))
            db.execute("INSERT INTO goals VALUES (?,?,?,?,?,?)",
                       (site + '-goal', site, 'Goal', 'pageview', '/' + site, '2026-11-01'))
    return source


def test_preview_does_not_mutate_database(tmp_path):
    path = populated(tmp_path)
    before = path.read_bytes()
    result = preview_purge(path, "alpha")
    assert result['mode'] == 'preview'
    assert result['deletion_counts'] == {table: 1 for table in
           ('sites', 'site_domains', 'sessions', 'events', 'goals')}
    assert path.read_bytes() == before
    assert not (tmp_path / 'backup.sqlite3').exists()


def test_site_purge_is_isolated_and_recoverable(tmp_path):
    path = populated(tmp_path)
    backup = tmp_path / 'backup.sqlite3'
    response = apply_purge(path, 'alpha', backup, 'alpha')
    assert response['mode'] == 'applied'
    assert response['deleted']['events'] == 1
    assert verify_backup(backup)['events'] == 2
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        for table in ('sites', 'site_domains', 'sessions', 'events', 'goals'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 1
            field = 'id' if table == 'sites' else 'site_id'
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE {field}=?',
                              ('bravo',)).fetchone()[0] == 1
    assert inspect_schema(path)['status'] == 'ready'
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 2


def test_confirmation_required_before_backup_or_deletion(tmp_path):
    source = populated(tmp_path)
    backup = tmp_path / 'backup.sqlite3'
    with pytest.raises(ValueError, match='confirmation'):
        apply_purge(source, 'alpha', backup, 'bravo')
    assert not backup.exists()
    assert preview_purge(source, 'alpha')['deletion_counts']['events'] == 1


def test_unknown_site_and_bad_source_cannot_create_backup(tmp_path):
    source = populated(tmp_path)
    backup = tmp_path / 'backup.sqlite3'
    with pytest.raises(ValueError, match='Unknown site'):
        apply_purge(source, 'ghost', backup, 'ghost')
    with pytest.raises(ValueError, match='existing regular file'):
        apply_purge(tmp_path / 'missing.db', 'alpha', backup, 'alpha')
    assert not backup.exists()


def test_failed_backup_does_not_delete(tmp_path):
    source = populated(tmp_path)
    dest = tmp_path / 'backup.sqlite3'
    dest.write_text('do not overwrite', encoding='utf-8')
    with pytest.raises(ValueError):
        apply_purge(source, 'alpha', dest, 'alpha')
    assert dest.read_text() == 'do not overwrite'
    assert preview_purge(source, 'alpha')['deletion_counts']['events'] == 1


def test_intervening_write_refuses_purge_and_preserves_backup(tmp_path, monkeypatch):
    source = populated(tmp_path)
    backup = tmp_path / 'backup.sqlite3'
    from analytics import purge
    original = purge.backup_database
    def mutate_after_backup(*args):
        evidence = original(*args)
        with sqlite3.connect(source) as db:
            db.execute("INSERT INTO goals VALUES (?,?,?,?,?,?)",
                       ('second', 'alpha', 'Another', 'event', 'signup', '2026-11-01'))
        return evidence
    monkeypatch.setattr(purge, 'backup_database', mutate_after_backup)
    with pytest.raises(RuntimeError, match='changed since backup'):
        apply_purge(source, 'alpha', backup, 'alpha')
    assert backup.exists() and verify_backup(backup)['goals'] == 2
    assert preview_purge(source, 'alpha')['deletion_counts']['goals'] == 2


def test_cli_rejects_unconfirmed_apply(tmp_path):
    source = populated(tmp_path)
    cmd = [sys.executable, '-m', 'analytics.purge', '--database', str(source),
           '--site-id', 'alpha', '--apply', '--backup-to', str(tmp_path/'backup.sqlite3')]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert '--confirm-site-id' in result.stderr
    assert preview_purge(source, 'alpha')['deletion_counts']['events'] == 1