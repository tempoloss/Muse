import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

PREFIX = "muse:v2:"
OUTAGE_S = 30.0
TIMEOUT_S = 0.2

log = structlog.get_logger()


class Cache(Protocol):
    async def get_or_compute[T](
        self, key: str, ttl: int, compute: Callable[[], Awaitable[T]]
    ) -> T: ...

    async def delete(self, *keys: str) -> None: ...


class NullCache:
    async def get_or_compute[T](self, key: str, ttl: int, compute: Callable[[], Awaitable[T]]) -> T:
        return await compute()

    async def delete(self, *keys: str) -> None:
        return None


class RedisCache:
    def __init__(self, url: str, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._redis = Redis.from_url(
            url,
            socket_timeout=TIMEOUT_S,
            socket_connect_timeout=TIMEOUT_S,
            retry=Retry(NoBackoff(), 0),
        )
        self._monotonic = monotonic
        self._down_until = 0.0

    def _up(self) -> bool:
        return self._monotonic() >= self._down_until

    def _failed(self) -> None:
        self._down_until = self._monotonic() + OUTAGE_S
        log.warning("cache: redis unavailable, serving uncached")

    async def get_or_compute[T](self, key: str, ttl: int, compute: Callable[[], Awaitable[T]]) -> T:
        if not self._up():
            return await compute()
        name = PREFIX + key
        try:
            hit = await self._redis.get(name)
        except RedisError:
            self._failed()
            return await compute()
        if hit is not None:
            cached: Any = json.loads(hit)
            return cached
        value = await compute()
        try:
            await self._redis.set(name, json.dumps(value, ensure_ascii=False), ex=ttl)
        except RedisError:
            self._failed()
        return value

    async def delete(self, *keys: str) -> None:
        if not keys or not self._up():
            return
        try:
            await self._redis.delete(*(PREFIX + key for key in keys))
        except RedisError:
            self._failed()

    async def close(self) -> None:
        await self._redis.aclose()
