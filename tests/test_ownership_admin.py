"""Offline binding demands independent operator review and a recoverable backup."""
import json
import sqlite3
import subprocess
import sys

import pytest
from analytics.backup import verify_backup
from analytics.ownership import has_site_permission
from analytics.ownership_admin import preview_owner_binding, apply_owner_binding
from analytics.storage import Storage
from analytics.schema_audit import inspect_schema


def two_sites(tmp_path):
    path=tmp_path/'analytics.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        for site in ('alpha','bravo'):
            db.execute('INSERT INTO sites VALUES (?,?,?,?)',
                       (site,site,json.dumps([f'{site}.example.com']),'2026-11-07'))
    return path


def args():
    return ['analytics:read','analytics:export']


def test_preview_is_readonly_and_does_not_autoassign(tmp_path):
    path=two_sites(tmp_path)
    before=path.read_bytes()
    report=preview_owner_binding(path,'alpha','tenant-a','subject-a',args())
    assert report['mode']=='preview' and report['requires_verified_backup']
    assert report['requires_verified_independent_ownership_evidence']
    assert path.read_bytes()==before
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0


def test_backup_confirmed_binding_is_isolated_and_recovers(tmp_path):
    path=two_sites(tmp_path)
    backup=tmp_path/'before.sqlite3'
    result=apply_owner_binding(path,'alpha','tenant-a','subject-a',args(),backup,'alpha','tenant-a')
    assert result['mode']=='applied'
    assert verify_backup(backup)['sites']==2
    with sqlite3.connect(path) as db:
        assert has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                   trusted_subject_id='subject-a',permission='analytics:read')
        assert has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                   trusted_subject_id='subject-a',permission='analytics:export')
        assert not has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                       trusted_subject_id='subject-a',permission='analytics:delete')
        assert not has_site_permission(db,site_id='bravo',trusted_tenant_id='tenant-a',
                                       trusted_subject_id='subject-a',permission='analytics:read')
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==2
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0
    assert inspect_schema(path)['status']=='ready'


def test_owner_can_never_be_silently_replaced(tmp_path):
    path=two_sites(tmp_path)
    apply_owner_binding(path,'alpha','tenant-a','subject-a',args(),
                        tmp_path/'backup-one.sqlite3','alpha','tenant-a')
    with pytest.raises(ValueError,match='already has a registered owner'):
        apply_owner_binding(path,'alpha','tenant-b','subject-b',['analytics:admin'],
                            tmp_path/'backup-two.sqlite3','alpha','tenant-b')
    assert not (tmp_path/'backup-two.sqlite3').exists()


def test_missing_confirmations_and_backup_overwrite_do_not_touch_data(tmp_path):
    path=two_sites(tmp_path)
    backup=tmp_path/'existing.sqlite3'
    with pytest.raises(ValueError,match='Confirmation'):
        apply_owner_binding(path,'alpha','tenant-a','subject-a',args(),
                            backup,'bravo','tenant-a')
    assert not backup.exists()
    backup.write_text('do not overwrite')
    with pytest.raises(ValueError):
        apply_owner_binding(path,'alpha','tenant-a','subject-a',args(),
                            backup,'alpha','tenant-a')
    assert backup.read_text()=='do not overwrite'
    assert preview_owner_binding(path,'alpha','tenant-a','subject-a',args())['mode']=='preview'


@pytest.mark.parametrize('site,tenant,subject,permissions',[
    ('not-here','tenant-a','subject-a',['analytics:read']),
    ('alpha','tenant with space','subject-a',['analytics:read']),
    ('alpha','tenant-a','subject-a',['analytics:delete','analytics:delete']),
    ('alpha','tenant-a','subject-a',[]),
    ('alpha','tenant-a','subject-a',['*']),
    ('alpha','tenant-a','bearer jwt\nheader',['analytics:read']),
])
def test_invalid_assignments_fail_closed_without_backup(tmp_path,site,tenant,subject,permissions):
    path=two_sites(tmp_path)
    with pytest.raises(ValueError):
        apply_owner_binding(path,site,tenant,subject,permissions,
                            tmp_path/'backup.sqlite3',site,tenant)
    assert not (tmp_path/'backup.sqlite3').exists()


def test_intervening_owner_write_rolls_back_and_retains_backup(tmp_path,monkeypatch):
    path=two_sites(tmp_path)
    backup=tmp_path/'backup.sqlite3'
    from analytics import ownership_admin
    original=ownership_admin.backup_database
    def competing_owner(*params):
        evidence=original(*params)
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO site_owners VALUES(?,?,?,?)',
                       ('alpha','tenant-b','2026-11-07','offline-operator'))
        return evidence
    monkeypatch.setattr(ownership_admin,'backup_database',competing_owner)
    with pytest.raises(RuntimeError,match='changed since verified backup'):
        apply_owner_binding(path,'alpha','tenant-a','subject-a',args(),backup,'alpha','tenant-a')
    assert backup.exists() and verify_backup(backup)['sites']==2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT tenant_id FROM site_owners').fetchone()[0]=='tenant-b'
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==0


def test_cli_defaults_to_preview_and_refuses_partial_apply(tmp_path):
    path=two_sites(tmp_path)
    cmd=[sys.executable,'-m','analytics.ownership_admin','--database',str(path),
         '--site-id','alpha','--tenant-id','tenant-a','--subject-id','subject-a',
         '--permissions','analytics:read']
    preview=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
    assert preview.returncode==0
    assert json.loads(preview.stdout)['mode']=='preview'
    invalid=subprocess.run(cmd+['--apply'],capture_output=True,text=True,timeout=10)
    assert invalid.returncode!=0 and '--confirm-tenant-id' in invalid.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0
