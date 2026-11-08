"""Explicit SQLite v0/v1->v2 upgrade, backup, preservation and fail-closed tests."""
import json
import sqlite3
from pathlib import Path
import subprocess
import sys

import pytest
from analytics.backup import verify_backup
from analytics.migrate import preview_migration, apply_migration
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def legacy(path, domain='example.com'):
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE site_permissions')
        db.execute('DROP TABLE site_owners')
        db.execute('DROP TABLE site_domains')
        db.execute('PRAGMA user_version=0')
        db.execute('INSERT INTO sites VALUES (?, ?, ?, ?)',
                   ('original', 'Name', json.dumps([domain]), '2026-10-01'))
        db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)',
                   ('visit', 'original', 'anon', '2026-10-01', '2026-10-01', 1))
        db.execute('INSERT INTO events(id,site_id,session_id,visitor_hash,ts,kind,path,hostname) '
                   'VALUES (?,?,?,?,?,?,?,?)',
                   ('event', 'original', 'visit', 'anon', '2026-10-01', 'pageview',
                    '/one', domain))
    return path


def test_upgrade_preview_is_nonmutating_and_start_fails_closed(tmp_path):
    path = legacy(tmp_path/'legacy.sqlite3')
    original = path.read_bytes()
    assert preview_migration(path)['action'] == 'apply-with-verified-backup'
    assert path.read_bytes() == original
    with pytest.raises(RuntimeError, match='unversioned'):
        Storage(str(path))
    assert path.read_bytes() == original


def test_known_legacy_data_is_preserved_and_proof_pending(tmp_path):
    path = legacy(tmp_path/'legacy.sqlite3')
    backup = tmp_path/'backup.sqlite3'
    result = apply_migration(path, backup)
    assert result['mode'] == 'applied'
    assert result['user_version'] == 2
    assert verify_backup(backup)['events'] == 1
    assert inspect_schema(backup)['status'] == 'migration-required'
    assert inspect_schema(path)['status'] == 'ready'
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
        proof = db.execute('SELECT domain,challenge,verified_at FROM site_domains').fetchone()
        assert proof[0] == 'example.com' and len(proof[1]) > 30 and proof[2] is None
    Storage(str(path))


def test_unversioned_but_domain_complete_adopts_without_resetting_proof(tmp_path):
    path=tmp_path/'unversioned.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE site_permissions')
        db.execute('DROP TABLE site_owners')
        db.execute('PRAGMA user_version=0')
        db.execute('INSERT INTO sites VALUES (?, ?, ?, ?)',
                   ('existing','One',json.dumps(['example.com']),'2026-10-01'))
        db.execute('INSERT INTO site_domains VALUES (?,?,?,?)',
                   ('existing','example.com','', '2026-10-02'))
    applied=apply_migration(path,tmp_path/'backup.sqlite3')
    assert applied['mode']=='applied'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT verified_at FROM site_domains').fetchone()[0]=='2026-10-02'


def test_cli_preview_is_safe_and_apply_requires_backup(tmp_path):
    path=legacy(tmp_path/'legacy.sqlite3')
    cmd=[sys.executable,'-m','analytics.migrate','--database',str(path)]
    preview=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
    assert preview.returncode==0
    assert json.loads(preview.stdout)['action']=='apply-with-verified-backup'
    no_backup=subprocess.run(cmd+['--apply'],capture_output=True,text=True,timeout=15)
    assert no_backup.returncode!=0
    assert 'requires --backup-to' in no_backup.stderr
    assert inspect_schema(path)['status']=='migration-required'


def test_migration_rejects_unknown_schemas_before_backup(tmp_path):
    path=tmp_path/'partial.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY)')
    with pytest.raises(ValueError,match='manual review'):
        apply_migration(path,tmp_path/'backup.sqlite3')
    assert not (tmp_path/'backup.sqlite3').exists()


def test_migration_refuses_backup_overwrite(tmp_path):
    path=legacy(tmp_path/'legacy.sqlite3')
    backup=tmp_path/'backup.sqlite3'
    backup.write_text('preserve')
    with pytest.raises(ValueError):
        apply_migration(path,backup)
    assert backup.read_text()=='preserve'
    assert inspect_schema(path)['status']=='migration-required'


def test_existing_schema_is_idempotent_without_backup(tmp_path):
    path=tmp_path/'new.sqlite3'
    Storage(str(path))
    result=apply_migration(path,tmp_path/'unused.sqlite3')
    assert result['mode']=='already-current' and result['backup'] is None
    assert not (tmp_path/'unused.sqlite3').exists()


def test_failed_migration_rolls_back_schema_and_keeps_backup(tmp_path, monkeypatch):
    path = legacy(tmp_path / 'legacy.sqlite3')
    backup = tmp_path / 'backup.sqlite3'

    def fail_random(_):
        raise RuntimeError('injected failure')

    monkeypatch.setattr('analytics.migrate.secrets.token_urlsafe', fail_random)
    with pytest.raises(RuntimeError, match='injected failure'):
        apply_migration(path, backup)
    assert verify_backup(backup)['events'] == 1
    report = inspect_schema(path)
    assert report['status'] == 'migration-required'
    assert report['missing_tables'] == ['site_domains']
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0


def test_started_database_rejects_broken_current_schema(tmp_path):
    path=tmp_path/'broken.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE goals')
    assert inspect_schema(path)['status']=='review-required'
    with pytest.raises(RuntimeError, match='incomplete'):
        Storage(str(path))
