"""Ownership v2 migration and prospective deny-by-default policy tests."""
import json
import sqlite3
import pytest

from analytics.backup import verify_backup
from analytics.migrate import preview_migration, apply_migration
from analytics.ownership import PERMISSIONS, has_site_permission
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def make_site(db):
    db.execute("INSERT INTO sites(id,name,domains,created_at) VALUES (?,?,?,?)",
               ('alpha', 'Example', json.dumps(['example.com']), '2026-11-07'))


def make_v1(path):
    Storage(str(path))  # current version-2 schema
    with sqlite3.connect(path) as db:
        make_site(db)
        db.execute('DROP TABLE site_permissions')
        db.execute('DROP TABLE site_owners')
        db.execute('PRAGMA user_version=1')
    return path


def test_new_database_has_zero_assigned_tenants(tmp_path):
    path=tmp_path / 'new.sqlite3'
    Storage(str(path))
    report=inspect_schema(path)
    assert report['status']=='ready' and report['user_version']==2
    with sqlite3.connect(path) as db:
        make_site(db)
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==0
        assert not has_site_permission(db,site_id='alpha', trusted_tenant_id='tenant-a',
                                       trusted_subject_id='subject-a',permission='analytics:read')


def test_v1_upgrade_is_explicit_atomic_and_preserves_existing_site(tmp_path):
    path=make_v1(tmp_path/'old.sqlite3')
    before=path.read_bytes()
    report=preview_migration(path)
    assert report['target_version']==2
    assert report['user_version']==1 and report['existing_site_ownership_remains_unassigned']
    assert path.read_bytes()==before
    with pytest.raises(RuntimeError, match='unversioned'):
        Storage(str(path))
    backup=tmp_path/'backup.sqlite3'
    result=apply_migration(path,backup)
    assert result['mode']=='applied' and result['user_version']==2
    assert inspect_schema(backup)['status']=='migration-required'
    assert verify_backup(backup)['sites']==1
    assert inspect_schema(path)['status']=='ready'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id FROM sites').fetchone()[0]=='alpha'
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==0
    Storage(str(path))


def test_v1_backup_must_be_exclusive(tmp_path):
    path=make_v1(tmp_path/'old.sqlite3')
    backup=tmp_path/'already.sqlite3'
    backup.write_bytes(b'preserve')
    with pytest.raises(ValueError):
        apply_migration(path,backup)
    assert backup.read_bytes()==b'preserve'
    assert inspect_schema(path)['status']=='migration-required'


def test_partial_ownership_schema_and_unknown_marker_refused(tmp_path):
    path=make_v1(tmp_path/'broken.sqlite3')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE site_owners(site_id TEXT)')
    assert inspect_schema(path)['status']=='review-required'
    with pytest.raises(ValueError,match='manual review'):
        apply_migration(path,tmp_path/'not-created.sqlite3')
    assert not (tmp_path/'not-created.sqlite3').exists()
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    assert inspect_schema(path)['status']=='review-required'


def test_signed_tenant_alone_is_not_permission_without_owner_and_membership(tmp_path):
    path=tmp_path/'fresh.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        make_site(db)
        assert not has_site_permission(db, site_id='alpha',trusted_tenant_id='tenant-a',
                                      trusted_subject_id='subject-a',permission='analytics:admin')
        db.execute("INSERT INTO site_owners VALUES (?,?,?,?)",
                   ('alpha', 'tenant-a', '2026-11-07','offline-operator'))
        assert not has_site_permission(db, site_id='alpha', trusted_tenant_id='tenant-a',
                                      trusted_subject_id='subject-a',permission='analytics:read')
        db.execute("INSERT INTO site_permissions VALUES (?,?,?,?)",
                   ('alpha','subject-a','analytics:read','2026-11-07'))
        assert has_site_permission(db,site_id='alpha',trusted_tenant_id='tenant-a',
                                   trusted_subject_id='subject-a',permission='analytics:read')
        for tenant,subject,site,permission in [
            ('tenant-b','subject-a','alpha','analytics:read'),
            ('tenant-a','subject-b','alpha','analytics:read'),
            ('tenant-a','subject-a','other','analytics:read'),
            ('tenant-a','subject-a','alpha','analytics:delete'),
            ('tenant-a','subject-a','alpha','read'),
        ]:
            assert not has_site_permission(db,site_id=site,trusted_tenant_id=tenant,
                                           trusted_subject_id=subject,permission=permission)
        for invalid in (None,'',12,[],False):
            assert not has_site_permission(db,site_id='alpha',trusted_tenant_id=invalid,
                                           trusted_subject_id='subject-a',permission='analytics:read')
        assert set(PERMISSIONS)=={'analytics:read','analytics:export','analytics:manage',
                                 'analytics:admin','analytics:delete'}


def test_owner_and_memberships_cascade_on_site_delete(tmp_path):
    path=tmp_path/'fresh.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        make_site(db)
        db.execute("INSERT INTO site_owners VALUES (?,?,?,?)",
                   ('alpha', 'tenant-a', '2026-11-07','offline-operator'))
        db.execute("INSERT INTO site_permissions VALUES (?,?,?,?)",
                   ('alpha','subject-a','analytics:read','2026-11-07'))
        db.execute("DELETE FROM sites WHERE id='alpha'")
        assert db.execute('SELECT COUNT(*) FROM site_owners').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM site_permissions').fetchone()[0]==0


def test_owner_table_constraint_tamper_is_detected(tmp_path):
    path=tmp_path/'fresh.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE site_permissions')
        db.execute('DROP TABLE site_owners')
        db.execute('CREATE TABLE site_owners (site_id TEXT, tenant_id TEXT, assigned_at TEXT, assigned_by TEXT)')
        db.execute('CREATE TABLE site_permissions (site_id TEXT, subject_id TEXT, permission TEXT, granted_at TEXT)')
    audit=inspect_schema(path)
    assert audit['status']=='review-required'
    assert set(audit['invalid_primary_keys']) >= {'site_owners','site_permissions'}
    with pytest.raises(RuntimeError,match='incomplete'):
        Storage(str(path))


def test_current_schema_rejects_owner_table_missing_required_columns(tmp_path):
    path=tmp_path / 'mangled.sqlite3'
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE site_permissions')
        db.execute('DROP TABLE site_owners')
        db.execute('CREATE TABLE site_owners(site_id TEXT PRIMARY KEY REFERENCES sites(id) '
                   'ON DELETE CASCADE, tenant_id TEXT NOT NULL, assigned_at TEXT NOT NULL)')
        db.execute('CREATE INDEX ix_site_owners_tenant ON site_owners(tenant_id,site_id)')
        db.execute('CREATE TABLE site_permissions(site_id TEXT NOT NULL REFERENCES '
                   'site_owners(site_id) ON DELETE CASCADE,subject_id TEXT,permission TEXT, '
                   'granted_at TEXT,PRIMARY KEY(site_id,subject_id,permission))')
        db.execute('CREATE INDEX ix_site_permissions_subject ON site_permissions(subject_id,site_id)')
    assert inspect_schema(path)['missing_columns']['site_owners'] == ['assigned_by']
    with pytest.raises(RuntimeError,match='incomplete'):
        Storage(str(path))
