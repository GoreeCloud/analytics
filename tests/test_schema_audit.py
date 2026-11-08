"""Read-only preflight, including old schemas, corruption and absent files."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def test_current_schema_audits_without_mutating(tmp_path):
    path = tmp_path / 'analytics.sqlite3'
    Storage(str(path))
    before = path.read_bytes()
    report = inspect_schema(path)
    assert report['status'] == 'ready'
    assert report['user_version'] == 2
    assert report['missing_columns'] == {}
    assert report['missing_tables'] == []
    assert report['schema_migration_performed'] is False
    assert path.read_bytes() == before


def test_legacy_sites_schema_fails_closed_without_upgrading(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY, name TEXT, domains TEXT, created_at TEXT)')
        db.execute('INSERT INTO sites VALUES (?, ?, ?, ?)',
                   ('legacy', 'Website', json.dumps(['example.com']), '2026-01-01'))
    before = path.read_bytes()
    report = inspect_schema(path)
    assert report['status'] == 'review-required'
    assert 'site_domains' in report['missing_tables']
    assert path.read_bytes() == before


def test_missing_schema_columns_reported(tmp_path):
    path = tmp_path / 'partial.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY, name TEXT)')
    report = inspect_schema(path)
    assert 'domains' in report['missing_columns']['sites']


def test_symlinks_missing_and_corrupt_files_fail_closed(tmp_path):
    path = tmp_path / 'absent.sqlite3'
    with pytest.raises(ValueError):
        inspect_schema(path)
    assert not path.exists()
    corrupt = tmp_path / 'corrupt.sqlite3'
    corrupt.write_bytes(b'not a database')
    with pytest.raises(ValueError):
        inspect_schema(corrupt)
    link = tmp_path / 'link.sqlite3'
    link.symlink_to(corrupt)
    with pytest.raises(ValueError):
        inspect_schema(link)


def test_cli_exit_status_reflects_manual_review_requirement(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sites (id TEXT PRIMARY KEY)')
    cmd = [sys.executable, '-m', 'analytics.schema_audit', '--database', str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout)['schema_migration_performed'] is False
    assert json.loads(result.stdout)['status'] == 'review-required'
