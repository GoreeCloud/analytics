"""Structural schema checks stop permissive/fake version-1 databases."""
import sqlite3
import pytest
from analytics.schema_audit import inspect_schema
from analytics.storage import Storage


def make_db(tmp_path):
    path = tmp_path / "analytics.sqlite3"
    Storage(str(path))
    assert inspect_schema(path)["status"] == "ready"
    return path


def test_missing_foreign_key_detected_and_start_refuses(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE site_domains")
        db.execute("CREATE TABLE site_domains (site_id TEXT NOT NULL,domain TEXT NOT NULL,"
                   "challenge TEXT NOT NULL,verified_at TEXT,PRIMARY KEY(site_id,domain))")
    report = inspect_schema(path)
    assert report["status"] == "review-required"
    assert report["missing_foreign_keys"]["site_domains"]
    with pytest.raises(RuntimeError, match="incomplete"):
        Storage(str(path))


def test_wrong_foreign_key_delete_action_detected(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE site_domains")
        db.execute("CREATE TABLE site_domains (site_id TEXT NOT NULL REFERENCES sites(id),"
                   "domain TEXT NOT NULL,challenge TEXT NOT NULL,verified_at TEXT,"
                   "PRIMARY KEY(site_id,domain))")
    assert inspect_schema(path)["missing_foreign_keys"]["site_domains"]


def test_missing_required_index_detected(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP INDEX ix_events_site_ts")
    assert "ix_events_site_ts" in inspect_schema(path)["missing_indexes"]["events"]
    with pytest.raises(RuntimeError):
        Storage(str(path))


def test_wrong_index_columns_detected(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP INDEX ix_goals_site")
        db.execute("CREATE INDEX ix_goals_site ON goals(name)")
    assert "ix_goals_site" in inspect_schema(path)["missing_indexes"]["goals"]


def test_missing_composite_primary_key_detected(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE site_domains")
        db.execute("CREATE TABLE site_domains (site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,"
                   "domain TEXT NOT NULL,challenge TEXT NOT NULL,verified_at TEXT,PRIMARY KEY(domain))")
    report = inspect_schema(path)
    assert report["status"] == "review-required"
    assert "site_domains" in report["invalid_primary_keys"]


def test_unmodified_database_reports_no_constraint_deficits(tmp_path):
    report = inspect_schema(make_db(tmp_path))
    assert report["invalid_primary_keys"] == []
    assert report["missing_foreign_keys"] == {}
    assert report["missing_indexes"] == {}
