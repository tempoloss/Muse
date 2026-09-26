import json
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from structlog.testing import capture_logs

from muse.shared.cache import PREFIX, RedisCache

REDIS_URL = os.environ.get("MUSE_TEST_REDIS", "")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="MUSE_TEST_REDIS is not set")
OUTAGE = "cache: redis unavailable, serving uncached"


class Counter:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    async def __call__(self) -> object:
        self.calls += 1
        return self.value


@pytest.fixture
async def cache() -> AsyncIterator[RedisCache]:
    cache = RedisCache(REDIS_URL)
    yield cache
    await cache.close()


@pytest.fixture
async def raw() -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_URL)
    yield client
    await client.aclose()


@needs_redis
async def test_a_value_is_computed_once_and_stored_as_readable_json(
    cache: RedisCache, raw: Redis
) -> None:
    key = f"test:{uuid4()}"
    compute = Counter({"name": "Кино", "ids": [1, 2]})

    first = await cache.get_or_compute(key, 60, compute)
    second = await cache.get_or_compute(key, 60, compute)

    assert first == second == {"name": "Кино", "ids": [1, 2]}
    assert compute.calls == 1
    assert await raw.get(PREFIX + key) == json.dumps(first, ensure_ascii=False).encode()
    assert 0 < await raw.ttl(PREFIX + key) <= 60
    await raw.delete(PREFIX + key)


@needs_redis
async def test_deleted_keys_are_computed_again(cache: RedisCache) -> None:
    keys = [f"test:{uuid4()}", f"test:{uuid4()}"]
    compute = Counter([1])
    for key in keys:
        await cache.get_or_compute(key, 60, compute)

    await cache.delete(*keys)
    for key in keys:
        await cache.get_or_compute(key, 60, compute)

    assert compute.calls == 4
    await cache.delete(*keys)


async def test_an_unreachable_redis_degrades_to_computing_with_one_warning_per_outage() -> None:
    now = [100.0]
    cache = RedisCache("redis://127.0.0.1:1/0", monotonic=lambda: now[0])
    compute = Counter(5)

    with capture_logs() as logs:
        results = [await cache.get_or_compute("k", 60, compute) for _ in range(3)]
        await cache.delete("k")
        now[0] += 31
        results.append(await cache.get_or_compute("k", 60, compute))
    await cache.close()

    assert results == [5, 5, 5, 5]
    assert compute.calls == 4
    assert [entry["event"] for entry in logs] == [OUTAGE, OUTAGE]
