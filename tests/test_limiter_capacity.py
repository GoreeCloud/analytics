"""Unique-key flooding must not grow anonymous rate limiter memory without bound."""
from analytics.app import SingleNodeLimiter


def test_unique_key_flood_is_bounded_and_fails_closed(monkeypatch):
    current = [3600.0]
    monkeypatch.setattr('analytics.app.time.monotonic', lambda: current[0])
    limiter = SingleNodeLimiter(limit=3)
    for n in range(10000):
        assert limiter.check(f'client-{n}')
    assert len(limiter._data) == 10000
    for n in range(10000, 10500):
        assert not limiter.check(f'client-{n}')
    assert len(limiter._data) == 10000
    assert limiter.check('client-1')
    current[0] += 61
    assert limiter.check('new-minute')
    assert len(limiter._data) == 1


def test_per_key_rate_limit_remains_enforced():
    limiter = SingleNodeLimiter(limit=2)
    assert limiter.check('same')
    assert limiter.check('same')
    assert not limiter.check('same')
