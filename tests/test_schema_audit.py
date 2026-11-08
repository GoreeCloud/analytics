"""Read-only schema preflight, including old schemas and corrupt files."""
import json
import sqlite3
import subprocess
import sys
import pytest
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def test_current_schema_is_read_without_writing(tmp_path):
    path = tmp_path / 'analytics.sqlite3'
    Storage(str(path))
    before = path.read_bytes()
    report = inspect_schema(path)
    assert report['status'] == 'current-structure-unversioned'
    assert report['user_version'] == 0
    assert report['missing_columns'] == {}
    assert report['missing_tables'] == []
    assert report['schema_migration_performed'] is False
    assert path.read_bytes() == before


def test_legacy_schema_is_flagged_and_not_upgraded(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY, name TEXT, domains TEXT, created_at TEXT)')
        db.execute('INSERT INTO sites VALUES (?, ?, ?, ?)',
                   ('legacy', 'Website', json.dumps(['example.com']), '2026-01-01'))
    before = path.read_bytes()
    report = inspect_schema(path)
    assert report['status'] == 'review-required'
    assert 'site_domains' in report['missing_tables']
    assert path.read_bytes() == before


def test_missing_columns_reported(tmp_path):
    path = tmp_path / 'partial.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY, name TEXT)')
    report = inspect_schema(path)
    assert 'domains' in report['missing_columns']['sites']


def test_bad_paths_and_corrupt_sqlite_fail_closed(tmp_path):
    missing = tmp_path / 'absent.sqlite3'
    with pytest.raises(ValueError):
        inspect_schema(missing)
    assert not missing.exists()
    corrupt = tmp_path / 'corrupt.sqlite3'
    corrupt.write_bytes(b'not a database')
    with pytest.raises(ValueError):
        inspect_schema(corrupt)
    link = tmp_path / 'link.sqlite3'
    link.symlink_to(corrupt)
    with pytest.raises(ValueError):
        inspect_schema(link)


def test_cli_returns_review_required_code(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY)')
    cmd = [sys.executable, '-m', 'analytics.schema_audit', '--database', str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'review-required'
    assert json.loads(result.stdout)['schema_migration_performed'] is False
