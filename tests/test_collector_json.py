"""Duplicate JSON members are invalid, not silently last-write-wins."""
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.config import Settings
from analytics.json_guard import unique_json_object


@pytest.mark.parametrize("json_value", [
    '{"site_id":"alpha","site_id":"beta"}',
    '{"properties":{"amount":1,"amount":2}}',
    '{"a":{"b":{"c":"one","c":"two"}}}',
])
def test_all_nested_duplicate_json_object_members_are_rejected(json_value):
    with pytest.raises(ValueError, match="Duplicate JSON"):
        json.loads(json_value, object_pairs_hook=unique_json_object)


def test_unique_json_members_and_arrays_remain_valid():
    data = json.loads('{"a":1,"b":[{"c":true},{"c":false}]}',
                      object_pairs_hook=unique_json_object)
    assert data == {"a": 1, "b": [{"c": True}, {"c": False}]}


def test_collector_refuses_duplicate_keys_before_database_write(tmp_path):
    settings = Settings(admin_token=secrets.token_urlsafe(48),
                        hash_secret=secrets.token_urlsafe(48),
                        database=str(tmp_path / "analytics.sqlite3"))
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + settings.admin_token}
    site = client.post("/api/v1/sites", headers=headers,
                       json={"name": "example", "domains": ["example.com"]})
    assert site.status_code == 201
    created = site.json()
    proof = created["verification"][0]
    client.app.state.txt_lookup = lambda _: [proof["record_value"]]
    assert client.post(f'/api/v1/sites/{created["id"]}/domains/verify',
                       headers=headers, json={"domain": "example.com"}).status_code == 200
    base = '{"site_id":' + json.dumps(created["id"]) + ','
    invalid = [
        base + '"url":"https://example.com/","url":"https://other.example/","type":"pageview"}',
        base + '"url":"https://example.com/","type":"event","name":"purchase",'
               '"properties":{"quantity":1,"quantity":2}}',
        base + '"url":"https://example.com/","type":"pageview",'
               '"properties":{"nested":{"a":1,"a":2}}}',
    ]
    for text in invalid:
        response = client.post("/api/v1/collect", content=text,
                               headers={"Origin": "https://example.com",
                                        "Content-Type": "text/plain"})
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid JSON"
    accepted = client.post("/api/v1/collect", json={"site_id": created["id"],
                           "url": "https://example.com/", "type": "pageview"},
                           headers={"Origin": "https://example.com"})
    assert accepted.status_code == 202
    summary = client.get(f'/api/v1/sites/{created["id"]}/summary',
                         headers=headers).json()
    assert summary["pageviews"] == 1
