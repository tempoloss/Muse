from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from dishka import Provider, Scope, provide
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.catalog.service import Catalog
from muse.settings import Settings
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, signed_in

SYNCED = "[00:04.00]первая\n[00:09.50][00:20.00]вторая"


@dataclass
class LrclibApi:
    answers: list[httpx.Response] = field(default_factory=list)
    seen: list[httpx.Request] = field(default_factory=list)
    user_agents: list[str | None] = field(default_factory=list)
    fallback: httpx.Response = field(default_factory=lambda: httpx.Response(404))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        self.user_agents.append(request.headers.get("user-agent"))
        return self.answers.pop(0) if self.answers else self.fallback


class LrclibProvider(Provider):
    def __init__(self, api: LrclibApi) -> None:
        super().__init__()
        self._api = api

    @provide(scope=Scope.APP)
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(self._api)) as client:
            yield client


@pytest.fixture
def api() -> LrclibApi:
    return LrclibApi()


@pytest.fixture
async def app(settings: Settings, api: LrclibApi) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[LrclibProvider(api)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


@pytest.fixture
def track_id(library: FixtureCatalog) -> int:
    [row] = fixture_rows(
        library, "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 1"
    )
    return int(row["id"])


def hit(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": 7,
        "trackName": track["title"],
        "artistName": track["artist"],
        "albumName": track["album"],
        "duration": track["dur"],
        "instrumental": False,
        "plainLyrics": "первая\nвторая",
        "syncedLyrics": SYNCED,
    }


async def test_the_route_serves_lrclib_through_the_wired_client_and_cache(
    app: Litestar, api: LrclibApi, track_id: int
) -> None:
    alice = await signed_in(app, "alice")
    track = await (await app.state.dishka_container.get(Catalog)).track(track_id)
    api.answers.append(httpx.Response(200, json=hit(track)))

    response = await alice.get(f"/api/lyrics/{track_id}")
    await alice.aclose()

    assert response.status_code == 200, response.text
    assert response.json() == {
        "synced": [
            {"at": 4.0, "text": "первая"},
            {"at": 9.5, "text": "вторая"},
            {"at": 20.0, "text": "вторая"},
        ],
        "plain": "первая\nвторая",
        "instrumental": False,
    }
    [request] = api.seen
    assert request.url.params["artist_name"] == track["artist"]
    assert request.url.params["track_name"] == track["title"]
    assert request.url.params["duration"] == str(track["dur"])
    assert api.user_agents == ["Muse (https://github.com/tempoloss/Muse)"]


async def test_a_dead_lrclib_is_503_through_the_wired_client(
    app: Litestar, api: LrclibApi, track_id: int
) -> None:
    alice = await signed_in(app, "alice")
    api.answers.append(httpx.Response(503, text="down"))

    response = await alice.get(f"/api/lyrics/{track_id}")
    await alice.aclose()

    assert (response.status_code, response.json()) == (503, {"detail": "lyrics unavailable"})
