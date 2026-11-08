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


def test_legacy_sites_migrate_pending_and_preserve_record(tmp_path):
    path=tmp_path/"old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sites (id TEXT PRIMARY KEY,name TEXT NOT NULL,domains TEXT NOT NULL,created_at TEXT NOT NULL)")
        db.execute("INSERT INTO sites VALUES('old','Example',?, '2026-01-01')",
                   (json.dumps(["example.com"]),))
    settings=Settings(admin_token="a"*48,hash_secret="b"*48,database=str(path))
    app=create_app(settings)
    client=TestClient(app)
    proof=client.get("/api/v1/sites",headers=auth()).json()[0]["verification"][0]
    assert not proof["verified"]
    assert visit(client,"old").status_code == 403
    app.state.txt_lookup=lambda _: [proof["record_value"]]
    assert client.post("/api/v1/sites/old/domains/verify",
                       json={"domain":"example.com"},headers=auth()).status_code == 200
    assert visit(client,"old").status_code == 202
    assert TestClient(create_app(settings)).get("/api/v1/sites",headers=auth()).json()[0]["verification"][0]["verified"]


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
