import pytest

from muse.identity.infra.ratelimit import LoginRateLimiter


def test_an_address_gets_five_attempts_per_window_and_blocked_tries_do_not_count() -> None:
    now = [1000.0]
    limiter = LoginRateLimiter(lambda: now[0])
    keys = ("ip:1.2.3.4", "login:alice")

    for step in range(5):
        now[0] = 1000.0 + step
        assert limiter.hit(keys) == 0.0
    now[0] = 1100.0
    assert limiter.hit(keys) == pytest.approx(800.0)
    assert limiter.hit(keys) == pytest.approx(800.0)

    now[0] = 1900.5
    assert limiter.hit(keys) == 0.0
    assert limiter.hit(keys) == pytest.approx(0.5)


def test_a_login_gets_ten_attempts_across_addresses() -> None:
    limiter = LoginRateLimiter(lambda: 50.0)

    allowed = [limiter.hit((f"ip:10.0.0.{n}", "login:alice")) for n in range(10)]

    assert allowed == [0.0] * 10
    assert limiter.hit(("ip:10.0.0.99", "login:alice")) == pytest.approx(900.0)
    assert limiter.hit(("ip:10.0.0.99", "login:bob")) == 0.0


def test_clearing_forgets_both_counters() -> None:
    limiter = LoginRateLimiter(lambda: 0.0)
    keys = ("ip:1.2.3.4", "login:alice")
    for _ in range(5):
        limiter.hit(keys)

    limiter.clear(keys)

    assert limiter.hit(keys) == 0.0
