"""An ownership revocation committed before event write must prevent ingestion."""
from fastapi.testclient import TestClient
from analytics.app import create_app
from analytics.config import Settings


def test_revoke_between_precheck_and_write_blocks_event(tmp_path, monkeypatch):
    app = create_app(Settings(admin_token='a' * 48, hash_secret='b' * 48,
                              database=str(tmp_path / 'analytics.sqlite3')))
    client = TestClient(app)
    auth = {'Authorization': 'Bearer ' + 'a' * 48}
    site = client.post('/api/v1/sites', headers=auth,
                       json={'name': 'One', 'domains': ['example.com']}).json()
    proof = site['verification'][0]
    app.state.txt_lookup = lambda _: [proof['record_value']]
    assert client.post(f'/api/v1/sites/{site["id"]}/domains/verify',
                       headers=auth, json={'domain': 'example.com'}).status_code == 200
    # Complete a separate database revocation after the initial proof check,
    # but before the collector begins BEGIN IMMEDIATE.
    original = app.state.site_limiter.check
    def revoke_then_continue(key):
        with app.state.storage.connect() as db:
            db.execute('UPDATE site_domains SET verified_at=NULL, challenge=? '
                       'WHERE site_id=? AND domain=?',
                       ('rotated-token', site['id'], 'example.com'))
        return original(key)
    monkeypatch.setattr(app.state.site_limiter, 'check', revoke_then_continue)
    result = client.post('/api/v1/collect',
                         headers={'Origin': 'https://example.com'},
                         json={'site_id': site['id'], 'type': 'pageview',
                               'url': 'https://example.com/pricing'})
    assert result.status_code == 403
    with app.state.storage.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
