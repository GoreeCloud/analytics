"""DNS ownership gate regression suite: all lookups are local fakes."""
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.config import Settings
from analytics.verification import DNSLookupUnavailable, read_txt_records


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(admin_token="a"*48, hash_secret="b"*48,
                              database=str(tmp_path / "analytics.sqlite3")))
    app.state.txt_lookup = lambda _: []
    return TestClient(app)


def auth():
    return {"Authorization": "Bearer " + "a"*48}


def register(client, domains=None):
    response = client.post("/api/v1/sites", headers=auth(), json={
        "name": "Domain proof", "domains": domains or ["example.com"]})
    assert response.status_code == 201, response.text
    return response.json()


def visit(client, site_id, domain="example.com"):
    return client.post("/api/v1/collect", headers={"Origin":f"https://{domain}"},
                       json={"site_id":site_id, "type":"pageview",
                             "url":f"https://{domain}/home"})


def test_registration_is_pending_and_ingest_fails_closed(client):
    site = register(client)
    proof = site["verification"][0]
    assert proof["verified"] is False
    assert proof["record_name"] == "_goreecloud-analytics.example.com"
    assert proof["record_value"].startswith("goreecloud-analytics-verification=")
    assert visit(client,site["id"]).status_code == 403
    assert client.get("/api/v1/sites").status_code == 401


def test_dns_exact_proof_requires_admin_and_cannot_be_replayed(client):
    site = register(client)
    proof = site["verification"][0]
    url=f'/api/v1/sites/{site["id"]}/domains/verify'
    assert client.post(url,json={"domain":"example.com"}).status_code == 401
    assert client.post(url,json={"domain":"wrong.com"},headers=auth()).status_code == 404
    assert client.post(url,json={"domain":"example.com"},headers=auth()).status_code == 409
    client.app.state.txt_lookup=lambda record: [proof["record_value"]+"wrong"]
    assert client.post(url,json={"domain":"example.com"},headers=auth()).status_code == 409
    assert visit(client,site["id"]).status_code == 403
    client.app.state.txt_lookup=lambda record: [proof["record_value"]] if record == proof["record_name"] else []
    assert client.post(url,json={"domain":"example.com"},headers=auth()).status_code == 200
    assert visit(client,site["id"]).status_code == 202
    assert client.post(url,json={"domain":"example.com"},headers=auth()).status_code == 200
    response=client.get("/api/v1/sites",headers=auth()).json()[0]["verification"][0]
    assert response["verified"] and response["record_value"] is None


def test_domain_proof_is_host_specific(client):
    site=register(client,["example.com","app.example.com"])
    first,second=site["verification"]
    client.app.state.txt_lookup=lambda name: [first["record_value"]] if name == first["record_name"] else []
    url=f'/api/v1/sites/{site["id"]}/domains/verify'
    assert client.post(url,json={"domain":first["domain"]},headers=auth()).status_code == 200
    assert visit(client,site["id"],first["domain"]).status_code == 202
    assert visit(client,site["id"],second["domain"]).status_code == 403


def test_legacy_registration_requires_explicit_backup_gated_upgrade(tmp_path):
    from analytics.storage import Storage
    from analytics.migrate import apply_migration
    path=tmp_path / "legacy.sqlite3"
    # Build a real complete schema, then emulate the pre-domain-verification
    # layout. The new application must never mutate that legacy DB on start.
    Storage(str(path))
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE site_domains")
        db.execute("PRAGMA user_version=0")
        db.execute("INSERT INTO sites VALUES ('old-site','Example',?, '2026-10-01')",
                   (json.dumps(['example.com']),))
    settings=Settings(admin_token="a"*48,hash_secret="b"*48,database=str(path))
    with pytest.raises(RuntimeError, match='unversioned'):
        create_app(settings)
    migrated=apply_migration(path, tmp_path/'pre-upgrade-backup.sqlite3')
    assert migrated['mode']=='applied'
    client=TestClient(create_app(settings))
    proof=client.get('/api/v1/sites',headers=auth()).json()[0]['verification'][0]
    assert proof['verified'] is False
    assert visit(client,'old-site').status_code == 403
    client.app.state.txt_lookup=lambda name: [proof['record_value']] if name==proof['record_name'] else []
    assert client.post('/api/v1/sites/old-site/domains/verify',headers=auth(),
                       json={'domain':'example.com'}).status_code == 200
    assert visit(client,'old-site').status_code == 202
    restarted=TestClient(create_app(settings))
    assert restarted.get('/api/v1/sites',headers=auth()).json()[0]['verification'][0]['verified'] is True


def test_dns_attempts_limited_and_resolver_errors_generic(client):
    site=register(client)
    client.app.state.dns_limiter.limit=2
    url=f'/api/v1/sites/{site["id"]}/domains/verify'
    for status in (409,409,429):
        assert client.post(url,json={"domain":"example.com"},headers=auth()).status_code == status
    other=register(client,["another.example.com"])
    def offline(_):
        raise DNSLookupUnavailable("private DNS detail")
    client.app.state.txt_lookup=offline
    failed=client.post(f'/api/v1/sites/{other["id"]}/domains/verify',
                       json={"domain":"another.example.com"},headers=auth())
    assert failed.status_code == 503
    assert "private DNS detail" not in failed.text


def test_txt_multisegment_answers_without_network(monkeypatch):
    import dns.resolver
    calls=[]
    class FakeResolver:
        def __init__(self,configure): assert configure
        def resolve(self,name,rdtype,search):
            calls.append((name,rdtype,search,self.timeout,self.lifetime))
            return [type("Answer",(),{"strings":[b"verification=",b"value"]})()]
    monkeypatch.setattr(dns.resolver,"Resolver",FakeResolver)
    assert read_txt_records("_goreecloud-analytics.example.com") == ["verification=value"]
    assert calls == [("_goreecloud-analytics.example.com.","TXT",False,1.0,3.0)]


def test_admin_revoke_rotates_dns_challenge_and_preserves_history(client):
    site = register(client)
    first = site["verification"][0]
    url = f'/api/v1/sites/{site["id"]}/domains'
    client.app.state.txt_lookup = lambda _: [first["record_value"]]
    assert client.post(url + "/verify", headers=auth(), json={"domain":"example.com"}).status_code == 200
    assert visit(client, site["id"]).status_code == 202
    assert client.post(url + "/revoke", json={"domain":"example.com"}).status_code == 401
    assert client.post(url + "/revoke", headers=auth(), json={"domain":"other.example.com"}).status_code == 404
    result = client.post(url + "/revoke", headers=auth(), json={"domain":"example.com"})
    assert result.status_code == 200
    new_proof = result.json()
    assert new_proof["verified"] is False
    assert new_proof["record_name"] == first["record_name"]
    assert new_proof["record_value"] != first["record_value"]
    assert visit(client, site["id"]).status_code == 403
    report = client.get(f'/api/v1/sites/{site["id"]}/summary', headers=auth()).json()
    assert report["pageviews"] == 1
    assert client.post(url + "/verify", headers=auth(), json={"domain":"example.com"}).status_code == 409
    client.app.state.txt_lookup = lambda _: [new_proof["record_value"]]
    assert client.post(url + "/verify", headers=auth(), json={"domain":"example.com"}).status_code == 200
    assert visit(client, site["id"]).status_code == 202
