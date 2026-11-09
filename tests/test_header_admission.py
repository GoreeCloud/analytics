"""Bound ASGI header processing before bearer-token and collector handlers."""
import secrets

from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.config import Settings


def client(tmp_path):
    app = create_app(Settings(admin_token=secrets.token_urlsafe(48),
                              hash_secret=secrets.token_urlsafe(48),
                              database=str(tmp_path / "analytics.db")))
    return TestClient(app)


def test_oversize_header_fails_before_authentication_and_preserves_security_headers(tmp_path):
    c = client(tmp_path)
    denied = c.get("/api/v1/sites", headers={"X-Giant": "a" * 8400})
    assert denied.status_code == 431
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert denied.headers["x-frame-options"] == "DENY"
    assert denied.headers["cache-control"] == "no-store"
    assert denied.headers["content-security-policy"].startswith("default-src 'none'")
    assert "a" * 50 not in denied.text
    assert c.get("/api/v1/sites").status_code == 401


def test_too_many_small_headers_are_rejected_before_collector_body(tmp_path):
    c = client(tmp_path)
    names = {f"X-Batch-{n}": "v" for n in range(70)}
    result = c.post("/api/v1/collect", content="not-json", headers=names)
    assert result.status_code == 431
    assert "Invalid JSON" not in result.text
    assert c.post("/api/v1/collect", content="not-json").status_code == 400


def test_cumulative_header_bytes_refused_even_for_small_fields(tmp_path):
    c = client(tmp_path)
    names = {f"X-Piece-{n}": "a" * 1000 for n in range(20)}
    result = c.get("/healthz", headers=names)
    assert result.status_code == 431
    assert c.get("/healthz").status_code == 200
