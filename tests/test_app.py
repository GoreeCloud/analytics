"""API, security, privacy and report regression tests."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.config import Settings


@pytest.fixture
def client(tmp_path):
    config = Settings(admin_token="admin-test-secret-" + "x" * 40,
                      hash_secret="hash-test-secret-" + "y" * 40,
                      database=str(tmp_path / "analytics.db"))
    return TestClient(create_app(config))


def auth(client):
    return {"Authorization": "Bearer " + "admin-test-secret-" + "x" * 40}


def site(client, name="Example", domain="example.com"):
    response = client.post("/api/v1/sites", headers=auth(client),
                           json={"name": name, "domains": [domain]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def track(client, site_id, type="pageview", url="https://example.com/home", name="", extra=None, headers=None):
    payload = {"site_id": site_id, "type": type, "url": url, "name": name, "properties": extra or {}}
    return client.post("/api/v1/collect", json=payload, headers=headers or {"Origin": "https://example.com", "User-Agent": "TestBrowser"})


def test_requires_auth_for_admin_and_distinct_secrets(client):
    assert client.get("/api/v1/sites").status_code == 401
    assert client.get("/api/v1/sites", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/api/v1/sites", json={"name":"x", "domains":["example.com"]}).status_code == 401


def test_sites_domain_validation_and_collection(client):
    response = client.post("/api/v1/sites", headers=auth(client), json={"name":"bad", "domains":["localhost"]})
    assert response.status_code == 422
    sid = site(client)
    assert track(client, sid).status_code == 202
    assert track(client, sid, type="event", name="signup", extra={"plan": "free"}).status_code == 202
    assert track(client, sid, url="https://bad.example/bogus").status_code == 403
    assert track(client, sid, headers={"Origin":"https://evil.com"}).status_code == 403
    assert track(client, sid, type="event", name="signup", extra={"email":"foo@example.com"}).status_code == 400
    data = client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()
    assert data["pageviews"] == 1
    assert data["visitors"] == 1
    assert data["visits"] == 1
    assert data["events"] == 1
    pages = client.get(f"/api/v1/sites/{sid}/breakdown?dimension=path", headers=auth(client)).json()
    assert pages[0] == {"label":"/home", "count":1}
    assert client.get(f"/api/v1/sites/{sid}/breakdown?dimension=unexpected", headers=auth(client)).status_code == 422
    assert client.get(f"/api/v1/sites/{sid}/realtime", headers=auth(client)).json()["visitors"] == 1


def test_funnel_order_and_csv_export(client):
    sid = site(client)
    assert track(client, sid, type="event", name="checkout").status_code == 202
    assert track(client, sid, type="event", name="signup").status_code == 202
    assert track(client, sid, type="event", name="checkout").status_code == 202
    funnel = client.get(f"/api/v1/sites/{sid}/funnel?first=signup&second=checkout", headers=auth(client)).json()
    assert funnel["started"] == 1
    assert funnel["completed"] == 1
    assert funnel["conversion_rate"] == 100.0
    export = client.get(f"/api/v1/sites/{sid}/export.csv", headers=auth(client))
    assert export.status_code == 200
    assert export.text.count("checkout") == 2
    assert client.get(f"/api/v1/sites/{sid}/export.csv").status_code == 401


def test_dnt_and_gpc_are_not_recorded(client):
    sid = site(client)
    assert track(client, sid, headers={"DNT":"1", "Origin":"https://example.com"}).status_code == 204
    assert track(client, sid, headers={"Sec-GPC":"1", "Origin":"https://example.com"}).status_code == 204
    assert client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()["pageviews"] == 0


def test_rejects_oversized_and_malformed_payloads(client):
    sid = site(client)
    assert client.post("/api/v1/collect", content="not-json").status_code == 400
    assert client.post("/api/v1/collect", content="x"*5000).status_code == 413
    assert track(client, sid, type="event", name="bad name").status_code == 400
    assert track(client, sid, type="event", name="click", extra={"password": "123"}).status_code == 400
    assert client.get(f"/api/v1/sites/{sid}/summary?start=2025-01-01&end=2026-11-05", headers=auth(client)).status_code == 422


def test_web_ui_and_safe_static_assets(client):
    assert client.get("/").status_code == 200
    assert "GoreeCloud" in client.get("/").text
    assert client.get("/assets/tracker.js").status_code == 200
    assert client.get("/assets/../../config.py").status_code == 404
    assert client.get("/").headers["x-frame-options"] == "DENY"


def test_site_isolation_and_privacy_redaction(client):
    alpha = site(client, "Alpha", "example.com")
    bravo = site(client, "Bravo", "bravo.example.com")
    response = track(client, alpha, url="https://example.com/customer/someone@example.com?utm_source=newsletter&utm_medium=cpc&utm_campaign=ab-test")
    assert response.status_code == 202
    response = track(client, bravo, url="https://bravo.example.com/dashboard", headers={"Origin":"https://bravo.example.com"})
    assert response.status_code == 202
    a = client.get(f"/api/v1/sites/{alpha}/breakdown?dimension=path", headers=auth(client)).json()
    assert a[0]["label"] == "/customer/:redacted"
    b = client.get(f"/api/v1/sites/{bravo}/summary", headers=auth(client)).json()
    assert b["pageviews"] == 1
    assert client.get(f"/api/v1/sites/{bravo}/summary").status_code == 401


def test_admin_env_requires_non_default_independent_secrets(monkeypatch):
    monkeypatch.setenv("GC_ANALYTICS_ADMIN_TOKEN", "weak")
    monkeypatch.setenv("GC_ANALYTICS_HASH_SECRET", "secret")
    with pytest.raises(RuntimeError):
        Settings.from_env()
    monkeypatch.setenv("GC_ANALYTICS_ADMIN_TOKEN", "x" * 40)
    monkeypatch.setenv("GC_ANALYTICS_HASH_SECRET", "x" * 40)
    with pytest.raises(RuntimeError):
        Settings.from_env()


def test_same_name_funnel_requires_two_separate_events(client):
    sid = site(client)
    assert track(client, sid, type="event", name="signup").status_code == 202
    endpoint = f"/api/v1/sites/{sid}/funnel?first=signup&second=signup"
    assert client.get(endpoint, headers=auth(client)).json()["completed"] == 0
    assert track(client, sid, type="event", name="signup").status_code == 202
    assert client.get(endpoint, headers=auth(client)).json()["completed"] == 1


def test_event_only_session_does_not_inflate_bounce_rate(client):
    sid = site(client)
    assert track(client, sid, type="event", name="signup").status_code == 202
    summary = client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()
    assert summary["visits"] == 1
    assert summary["bounce_rate"] == 0


def test_encoded_identifiers_and_email_property_values_are_not_saved(client):
    sid = site(client)
    result = track(client, sid, url="https://example.com/users/person%40example.com")
    assert result.status_code == 202
    pages = client.get(f"/api/v1/sites/{sid}/breakdown?dimension=path", headers=auth(client)).json()
    assert pages[0]["label"] == "/users/:redacted"
    assert track(client, sid, type="event", name="search", extra={"query": "person@example.com"}).status_code == 400


def test_oversized_chunked_payload_does_not_require_content_length(client):
    # The API must enforce its own incremental limit, even for streaming bodies.
    def oversized():
        yield b'{' + b' ' * 2048
        yield b' ' * 2048 + b'}'
    response = client.post('/api/v1/collect', content=oversized(),
                           headers={'Content-Type': 'text/plain'})
    assert response.status_code == 413


def test_retention_preview_and_explicit_apply_preserve_recent_visits(client):
    from datetime import datetime, timedelta, timezone
    from analytics.maintenance import retention_report
    sid = site(client)
    assert track(client, sid, url="https://example.com/old").status_code == 202
    store = client.app.state.storage
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=120)).isoformat(timespec="milliseconds")
    with store.connect() as db:
        db.execute("UPDATE events SET ts=?", (old,))
        db.execute("UPDATE sessions SET first_seen=?, last_seen=?", (old, old))
    prev = retention_report(store, 90, now=now)
    assert prev["mode"] == "preview" and prev["events"] == 1
    assert client.get(f"/api/v1/sites/{sid}/summary?start={old[:10]}&end={old[:10]}",
                      headers=auth(client)).json()["pageviews"] == 1
    applied = retention_report(store, 90, apply=True, now=now)
    assert applied["events"] == 1 and applied["expired_sessions"] == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_retention_rejects_invalid_windows(client):
    from analytics.maintenance import retention_report
    for days in (0, -1, 3651):
        with pytest.raises(ValueError):
            retention_report(client.app.state.storage, days)


def test_retention_command_refuses_missing_database(tmp_path):
    import subprocess
    import sys
    proc = subprocess.run([sys.executable, '-m', 'analytics.maintenance',
                           '--database', str(tmp_path / 'missing.db'), '--apply'],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0
    assert 'existing SQLite database' in proc.stderr
    assert not (tmp_path / 'missing.db').exists()


def test_malformed_urls_origins_and_referrers_never_crash_collector(client):
    sid = site(client)
    assert track(client, sid, url="http://[broken").status_code == 400
    assert track(client, sid, headers={"Origin": "http://[broken"}).status_code == 403
    payload = {"site_id": sid, "type": "pageview", "url": "https://example.com/home",
               "referrer": "http://[broken"}
    response = client.post('/api/v1/collect', json=payload, headers={"Origin":"https://example.com"})
    assert response.status_code == 202
    rows = client.get(f'/api/v1/sites/{sid}/breakdown?dimension=referrer', headers=auth(client)).json()
    assert rows[0]["label"] == ""


def test_blank_site_name_rejected(client):
    res = client.post('/api/v1/sites', json={'name':'   ','domains':['example.com']},
                      headers=auth(client))
    assert res.status_code == 422


def test_concurrent_events_share_single_visit(client):
    from concurrent.futures import ThreadPoolExecutor
    sid = site(client)
    with ThreadPoolExecutor(max_workers=6) as workers:
        statuses = list(workers.map(lambda _: track(client, sid).status_code, range(12)))
    assert statuses == [202] * 12
    data = client.get(f'/api/v1/sites/{sid}/summary', headers=auth(client)).json()
    assert data['pageviews'] == 12
    assert data['visits'] == 1


def test_saved_event_and_pageview_goals_are_authorized_and_site_scoped(client):
    sid = site(client)
    other = site(client, name='Other', domain='other.example.com')
    assert track(client, sid, type='pageview', url='https://example.com/pricing').status_code == 202
    assert track(client, sid, type='event', name='signup').status_code == 202
    assert track(client, sid, type='event', name='signup').status_code == 202
    payload = {'name':'New registrations', 'kind':'event', 'target':'signup'}
    assert client.post(f'/api/v1/sites/{sid}/goals',json=payload).status_code == 401
    created = client.post(f'/api/v1/sites/{sid}/goals', json=payload,headers=auth(client))
    assert created.status_code == 201
    assert client.post(f'/api/v1/sites/{sid}/goals',json=payload,headers=auth(client)).status_code == 409
    assert client.post(f'/api/v1/sites/{sid}/goals', json={'name':'Pricing', 'kind':'pageview','target':'/pricing'},headers=auth(client)).status_code == 201
    result = client.get(f'/api/v1/sites/{sid}/goals',headers=auth(client)).json()
    assert len(result) == 2
    assert all(g['converting_visits'] == 1 for g in result)
    assert all(g['visit_conversion_rate'] == 100.0 for g in result)
    assert client.get(f'/api/v1/sites/{other}/goals',headers=auth(client)).json() == []
    assert client.get(f'/api/v1/sites/{sid}/goals').status_code == 401
    assert client.post(f'/api/v1/sites/{sid}/goals',json={'name':'PII', 'kind':'pageview','target':'/user/name@example.com'},headers=auth(client)).status_code == 422


def test_backup_is_verified_consistent_and_does_not_replace_existing_files(client, tmp_path):
    from analytics.backup import backup_database, verify_backup
    sid = site(client)
    assert track(client, sid, url="https://example.com/first").status_code == 202
    store = client.app.state.storage
    target = tmp_path / "snapshot.sqlite3"
    evidence = backup_database(store.path, target)
    assert evidence["status"] == "verified"
    assert evidence["events"] == 1 and evidence["sites"] == 1
    assert target.stat().st_mode & 0o077 == 0  # no group/world access
    assert track(client, sid, url="https://example.com/second").status_code == 202
    assert verify_backup(target)["events"] == 1  # consistent point-in-time copy
    with pytest.raises(ValueError, match="new, distinct"):
        backup_database(store.path, target)
    assert verify_backup(target)["events"] == 1
    assert client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()["pageviews"] == 2


def test_backup_refuses_missing_source_bad_schema_and_nonexistent_output_directory(tmp_path):
    from analytics.backup import backup_database, verify_backup
    source = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError):
        backup_database(source, tmp_path / "out.sqlite3")
    assert not source.exists()
    source.write_text("unrelated text")
    with pytest.raises(ValueError):
        verify_backup(source)
    assert not (tmp_path / "out.sqlite3").exists()
    with pytest.raises(ValueError):
        backup_database(source, tmp_path / "not-a-folder" / "out.sqlite3")


def test_retention_apply_cli_requires_and_verifies_backup(client, tmp_path):
    import subprocess
    import sys
    from analytics.backup import verify_backup
    sid = site(client)
    assert track(client, sid, url="https://example.com/old").status_code == 202
    store = client.app.state.storage
    command = [sys.executable, "-m", "analytics.maintenance", "--database", store.path, "--days", "90", "--apply"]
    refused = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert refused.returncode != 0
    assert "--backup-to" in refused.stderr
    output = tmp_path / "pre-prune.sqlite3"
    completed = subprocess.run(command + ["--backup-to", str(output)], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert verify_backup(output)["events"] == 1
    assert '"mode": "applied"' in completed.stdout
    assert '"status": "verified"' in completed.stdout
    with pytest.raises(ValueError):
        from analytics.backup import backup_database
        backup_database(store.path, output)


def test_rate_limit_cannot_be_bypassed_by_rotating_user_agents(client):
    sid = site(client)
    client.app.state.ip_limiter.limit = 3
    for i in range(3):
        response = track(client, sid, headers={"User-Agent": f"fingerprint-{i}"})
        assert response.status_code == 202
    assert track(client, sid, headers={"User-Agent": "fingerprint-4"}).status_code == 429
    assert client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()["pageviews"] == 3


def test_site_limit_is_separate_from_anonymous_key_limit(client):
    sid = site(client)
    client.app.state.site_limiter.limit = 2
    assert track(client, sid).status_code == 202
    assert track(client, sid).status_code == 202
    assert track(client, sid).status_code == 429
    assert client.get(f"/api/v1/sites/{sid}/summary", headers=auth(client)).json()["pageviews"] == 2


def test_timeseries_includes_zero_traffic_days(client):
    from datetime import datetime, timezone, timedelta
    sid = site(client)
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    assert track(client, sid).status_code == 202
    result = client.get(f"/api/v1/sites/{sid}/timeseries?start={yesterday}&end={today}",
                        headers=auth(client))
    assert result.status_code == 200
    rows = result.json()
    assert len(rows) == 2
    assert rows[0] == {"day": yesterday.isoformat(), "pageviews": 0, "visitors": 0}
    assert rows[1]["pageviews"] == 1


def test_restore_is_validated_and_never_overwrites_live_database(client, tmp_path):
    from analytics.backup import backup_database, restore_database, verify_backup
    sid = site(client)
    assert track(client, sid).status_code == 202
    live = client.app.state.storage.path
    backup = tmp_path / "snapshot.sqlite3"
    restored = tmp_path / "recovered.sqlite3"
    backup_database(live, backup)
    result = restore_database(backup, restored)
    assert result["action"] == "restore"
    assert verify_backup(restored)["events"] == 1
    assert verify_backup(live)["events"] == 1
    with pytest.raises(ValueError):
        restore_database(backup, live)
    with pytest.raises(ValueError):
        restore_database(backup, restored)
    assert verify_backup(live)["events"] == 1


def test_backup_command_checks_its_snapshot_and_refuses_overwrite(client, tmp_path):
    import json
    import subprocess
    import sys
    sid = site(client)
    assert track(client, sid).status_code == 202
    snapshot = tmp_path / "backup.sqlite3"
    base = [sys.executable, "-m", "analytics.backup"]
    created = subprocess.run(base + ["--database", client.app.state.storage.path,
                                 "--output", str(snapshot)], capture_output=True, text=True, timeout=10)
    assert created.returncode == 0, created.stderr
    assert json.loads(created.stdout)["events"] == 1
    checked = subprocess.run(base + ["--verify-only", str(snapshot)],
                             capture_output=True, text=True, timeout=10)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["status"] == "verified"
    duplicate = subprocess.run(base + ["--database", client.app.state.storage.path,
                                   "--output", str(snapshot)], capture_output=True, text=True, timeout=10)
    assert duplicate.returncode != 0
    assert "new, distinct" in duplicate.stderr


def test_new_sqlite_database_is_owner_only_and_symlinks_are_rejected(tmp_path):
    from analytics.storage import Storage
    db_path = tmp_path / "private" / "analytics.sqlite3"
    Storage(str(db_path))
    assert db_path.is_file()
    assert db_path.stat().st_mode & 0o077 == 0
    symlink = tmp_path / "another.sqlite3"
    symlink.symlink_to(db_path)
    with pytest.raises(ValueError, match="symbolic link"):
        Storage(str(symlink))
