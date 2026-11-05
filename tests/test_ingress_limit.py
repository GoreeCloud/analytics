"""Prevent repeated malformed collector requests from evading per-client limits."""
import secrets
from fastapi.testclient import TestClient
from analytics.app import create_app
from analytics.config import Settings


def test_malformed_requests_consume_ingress_budget(tmp_path):
    app = create_app(Settings(
        admin_token=secrets.token_urlsafe(48),
        hash_secret=secrets.token_urlsafe(48),
        database=str(tmp_path / 'collector.db'),
    ))
    app.state.ingress_limiter.limit = 2
    client = TestClient(app)
    assert client.post('/api/v1/collect', content='bad-payload').status_code == 400
    assert client.post('/api/v1/collect', content='bad-payload').status_code == 400
    assert client.post('/api/v1/collect', content='bad-payload').status_code == 429
