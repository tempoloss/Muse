from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from dishka import Provider, Scope, provide
from litestar import Litestar

from muse.shared.clock import Clock, ZonedClock

ORIGIN = "https://testserver.local"
WRITE = {"Origin": ORIGIN}
PASSWORDS = {"alice": "test-pass-alice", "bob": "test-pass-bob"}


def browser(app: Litestar, **headers: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=cast("Any", app))
    return httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers=headers)


async def signed_in(app: Litestar, login: str) -> httpx.AsyncClient:
    client = browser(app)
    response = await client.post(
        "/api/login", json={"login": login, "password": PASSWORDS[login]}, headers=WRITE
    )
    assert response.status_code == 200, response.text
    return client


class ManualClock(ZonedClock):
    def __init__(self, ms: int, zone: str = "UTC") -> None:
        super().__init__(ZoneInfo(zone))
        self.ms = ms

    def now_ms(self) -> int:
        return self.ms

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.ms / 1000, self.zone)


class ManualClockProvider(Provider):
    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._clock = clock

    @provide(scope=Scope.APP)
    def clock(self) -> Clock:
        return self._clock
