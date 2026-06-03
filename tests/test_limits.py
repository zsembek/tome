"""WI-2.3: rate limiting + upload size cap."""
import pytest

from api.ratelimit import RateLimiter


@pytest.mark.unit
def test_token_bucket():
    t = [0.0]
    rl = RateLimiter(per_min=60, burst=2, clock=lambda: t[0])   # 1 token/s, cap 2
    assert rl.allow("k") and rl.allow("k")     # 2 -> 0
    assert not rl.allow("k")                   # empty -> blocked
    t[0] = 1.0                                 # refill 1 token
    assert rl.allow("k")
    assert not rl.allow("k")


@pytest.mark.unit
def test_rate_limiter_disabled():
    rl = RateLimiter(per_min=0)
    assert rl.enabled is False
    assert all(rl.allow("k") for _ in range(100))


@pytest.mark.integration
def test_rate_limit_returns_429(api_client):
    import api.main as m
    saved = m._limiter
    m._limiter = RateLimiter(per_min=60, burst=1)
    try:
        codes = [api_client.get("/v1/folders").status_code for _ in range(3)]
        assert 429 in codes
    finally:
        m._limiter = saved


@pytest.mark.integration
def test_upload_too_large_returns_413(api_client):
    import api.main as m
    from tome.config import get_config
    saved_lim, saved_cap = m._limiter, get_config().max_upload_mb
    m._limiter = RateLimiter(per_min=0)
    get_config().max_upload_mb = 1
    try:
        big = b"x" * (2 * 1024 * 1024)   # 2 MB > 1 MB cap
        r = api_client.post("/v1/documents",
                            files={"file": ("big.bin", big, "application/octet-stream")},
                            data={"auto_file": "true"})
        assert r.status_code == 413
    finally:
        m._limiter, get_config().max_upload_mb = saved_lim, saved_cap
