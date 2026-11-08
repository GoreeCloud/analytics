"""Explicit offline revocation protects unrelated grants and rollback data."""
import json
import sqlite3
import subprocess
import sys

import pytest

from analytics.backup import verify_backup
from analytics.permissions_admin import (preview_permission_revocation,
                                         apply_permission_revocation)
from analytics.ownership import has_site_permission
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def data(tmp_path):
    path = tmp_path/'analytics.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for site,tenant in [('alpha','tenant-a'),('bravo','tenant-b')]:
            db.execute('INSERT INTO sites VALUES(?,?,?,?)',
                       (site,site,json.dumps([f'{site}.example.com']), '2026-11-07'))
            db.execute('INSERT INTO site_owners VALUES(?,?,?,?)',
                       (site,tenant,'2026-11-07','offline-operator'))
        for site,principal,permission in [
            ('alpha','alice','analytics:read'),
            ('alpha','alice','analytics:export'),
            ('alpha','bob','analytics:read'),
            ('bravo','alice','analytics:read')]:
            db.execute('INSERT INTO site_permissions VALUES(?,?,?,?)',
                       (site,principal,permission,'2026-11-07'))
    return path


def args():
    return ('alpha','tenant-a','alice','analytics:export')


def test_preview_has_no_side_effects(tmp_path):
    path=data(tmp_path)
    before=path.read_bytes()
    report=preview_permission_revocation(path,*args())
    assert report['mode']=='preview' and report['verified_backup_required']
    assert report['site_permissions_before']==3
    assert path.read_bytes()==before


def test_revokes_only_one_grant_and_preserves_recoverable_backup(tmp_path):
    path=data(tmp_path)
    backup=tmp_path/'before.sqlite3'
    result=apply_permission_revocation(path,*args(),backup,*args())
    assert result['mode']=='applied' and result['site_permissions_after']==2
    assert verify_backup(backup)['sites']==2
    assert backup.stat().st_mode & 0o777==0o600
    with sqlite3.connect(path) as db:
        assert not has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                       trusted_subject_id='alice',permission='analytics:export')
        assert has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                   trusted_subject_id='alice',permission='analytics:read')
        assert has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                   trusted_subject_id='bob',permission='analytics:read')
        assert has_site_permission(db,site_id='bravo',trusted_tenant_id='tenant-b',
                                   trusted_subject_id='alice',permission='analytics:read')
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==4
    assert inspect_schema(path)['status']=='ready'
    with pytest.raises(ValueError,match='Exact permission grant'):
        preview_permission_revocation(path,*args())


@pytest.mark.parametrize('change',[
    ('bravo','tenant-a','alice','analytics:export'),
    ('alpha','tenant-b','alice','analytics:export'),
    ('alpha','tenant-a','eve','analytics:export'),
    ('alpha','tenant-a','alice','analytics:delete'),
    ('alpha','tenant-a','alice','*'),
    ('alpha','tenant-a','alice','analytics:read\n'),
])
def test_wrong_binding_and_permission_refused(tmp_path,change):
    path=data(tmp_path)
    backup=tmp_path/'before.sqlite3'
    with pytest.raises(ValueError):
        apply_permission_revocation(path,*change,backup,*change)
    assert not backup.exists()


def test_confirmation_mismatch_prevents_backup_or_change(tmp_path):
    path=data(tmp_path)
    backup=tmp_path/'before.sqlite3'
    for confirm in [
        ('bravo','tenant-a','alice','analytics:export'),
        ('alpha','tenant-b','alice','analytics:export'),
        ('alpha','tenant-a','bob','analytics:export'),
        ('alpha','tenant-a','alice','analytics:read')]:
        with pytest.raises(ValueError,match='Every confirmation'):
            apply_permission_revocation(path,*args(),backup,*confirm)
    assert not backup.exists()


def test_backup_must_be_exclusive_and_cannot_be_overwritten(tmp_path):
    path=data(tmp_path)
    backup=tmp_path/'before.sqlite3'
    backup.write_bytes(b'preserve')
    with pytest.raises(ValueError):
        apply_permission_revocation(path,*args(),backup,*args())
    assert backup.read_bytes()==b'preserve'


def test_concurrent_permission_change_refuses_and_preserves_backup(tmp_path,monkeypatch):
    path=data(tmp_path)
    backup=tmp_path/'before.sqlite3'
    from analytics import permissions_admin
    actual=permissions_admin.backup_database
    def conflicting(*values):
        evidence=actual(*values)
        with sqlite3.connect(path) as db:
            db.execute("UPDATE site_permissions SET granted_at='CHANGED' WHERE "
                       "site_id='alpha' AND subject_id='alice' AND permission='analytics:export'")
        return evidence
    monkeypatch.setattr(permissions_admin,'backup_database',conflicting)
    with pytest.raises(RuntimeError,match='changed since backup'):
        apply_permission_revocation(path,*args(),backup,*args())
    assert backup.exists() and verify_backup(backup)['sites']==2
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT granted_at FROM site_permissions WHERE permission='analytics:export'").fetchone()[0]=='CHANGED'


def test_cli_preview_and_missing_confirmations(tmp_path):
    path=data(tmp_path)
    command=[sys.executable,'-m','analytics.permissions_admin','--database',str(path),
             '--site-id','alpha','--tenant-id','tenant-a','--subject-id','alice',
             '--permission','analytics:export']
    preview=subprocess.run(command,capture_output=True,text=True,timeout=10)
    assert preview.returncode==0 and json.loads(preview.stdout)['mode']=='preview'
    refusal=subprocess.run(command+['--apply'],capture_output=True,text=True,timeout=10)
    assert refusal.returncode!=0 and 'all four' in refusal.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==4
