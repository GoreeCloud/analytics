"""Collector must not reflect noncanonical or malformed Origin headers."""
import secrets
import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.config import Settings
from analytics.origin import valid_serialized_origin


@pytest.mark.parametrize("origin", [
    "https://example.com/", "https://example.com/private",
    "https://example.com?access_token=secret",
    "https://example.com#fragment", "https://example.com:99999",
    "https://example.com:", "https://example.com:00080",
    "https://EXAMPLE.com", "HTTPS://example.com",
    "https://example.com@evil.com", "null", "file://example.com",
    "http://[broken", "https://example.com\t",
    "https://example.com https://evil.com",
])
def test_malformed_origin_syntax_is_rejected(origin):
    assert not valid_serialized_origin(origin, "example.com")


@pytest.mark.parametrize("origin", [
    "https://example.com", "http://example.com",
    "https://example.com:8443", "http://example.com:8080",
])
def test_canonical_same_site_origins_accepted(origin):
    assert valid_serialized_origin(origin, "example.com")


def test_collector_rejects_bad_origin_without_event_persistence(tmp_path):
    settings = Settings(admin_token=secrets.token_urlsafe(48),
                        hash_secret=secrets.token_urlsafe(48),
                        database=str(tmp_path / "db.sqlite3"))
    client = TestClient(create_app(settings))
    auth = {"Authorization": "Bearer " + settings.admin_token}
    created = client.post("/api/v1/sites", json={"name": "Example",
                        "domains": ["example.com"]}, headers=auth)
    assert created.status_code == 201
    site = created.json()
    proof = site["verification"][0]
    client.app.state.txt_lookup = lambda _: [proof["record_value"]]
    verified = client.post(f'/api/v1/sites/{site["id"]}/domains/verify',
                           headers=auth, json={"domain": "example.com"})
    assert verified.status_code == 200
    payload = {"site_id": site["id"], "type": "pageview",
               "url": "https://example.com/"}
    for invalid in ("https://example.com/hidden?token=x",
                    "https://example.com:99999"):
        denied = client.post("/api/v1/collect", json=payload,
                             headers={"Origin": invalid})
        assert denied.status_code == 403
        assert "access-control-allow-origin" not in denied.headers
    accepted = client.post("/api/v1/collect", json=payload,
                           headers={"Origin": "https://example.com"})
    assert accepted.status_code == 202
    assert accepted.headers["access-control-allow-origin"] == "https://example.com"
    assert client.get(f'/api/v1/sites/{site["id"]}/summary',
                      headers=auth).json()["pageviews"] == 1
