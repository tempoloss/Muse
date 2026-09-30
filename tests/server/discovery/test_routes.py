from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from dishka import Provider, Scope, provide
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.settings import Settings
from muse.shared.cache import Cache
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, WRITE, ManualClock, ManualClockProvider, signed_in

NOW_MS = 1_800_000_000_000
TODAY = "2027-01-15"
DAY_MS = 86_400_000
TRACK_KEYS = {"id", "num", "title", "dur", "album_id", "album", "artist"}


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    async def get_or_compute[T](self, key: str, ttl: int, compute: Callable[[], Awaitable[T]]) -> T:
        if key not in self.values:
            self.values[key] = await compute()
            self.ttls[key] = ttl
        return self.values[key]

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)


class MemoryCacheProvider(Provider):
    def __init__(self, cache: MemoryCache) -> None:
        super().__init__()
        self._cache = cache

    @provide(scope=Scope.APP)
    def cache(self) -> Cache:
        return self._cache


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(NOW_MS)


@pytest.fixture
async def app(settings: Settings, clock: ManualClock) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[ManualClockProvider(clock)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


def first_id(library: FixtureCatalog, sql: str, *params: object) -> int:
    return fixture_rows(library, sql, params)[0][0]


async def test_radio_follows_a_single_song(bob: httpx.AsyncClient, library: FixtureCatalog) -> None:
    seed = first_id(library, "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id")
    other = first_id(library, "SELECT id FROM tracks WHERE status='ok' AND id<>? ORDER BY id", seed)

    response = await bob.get(f"/api/radio/{seed}", params={"exclude": f"{other},x"})

    assert response.status_code == 200, response.text
    body = response.json()
    ids = [item["id"] for item in body["tracks"]]
    assert body["seed"] == seed
    assert len(ids) == len(set(ids)) == 25
    assert not {seed, other} & set(ids)
    assert max(Counter(item["artist"] for item in body["tracks"]).values()) <= 3
    assert set(body["tracks"][0]) == TRACK_KEYS
    heard = ids[0]
    report = {
        "track_id": heard,
        "started_at": NOW_MS - 5000,
        "listened_ms": 40000,
        "completed": False,
        "skipped": False,
        "source": "radio",
    }
    assert (await bob.post("/api/plays", json=report, headers=WRITE)).status_code == 204
    again = await bob.get(f"/api/radio/{seed}", params={"n": 50})
    assert heard not in [item["id"] for item in again.json()["tracks"]]
    missing = await bob.get("/api/radio/999999999")
    assert (missing.status_code, missing.json()) == (404, {"detail": "no track"})


@pytest.mark.parametrize("count", [4, 51])
async def test_radio_length_stays_between_5_and_50(
    bob: httpx.AsyncClient, library: FixtureCatalog, count: int
) -> None:
    seed = first_id(library, "SELECT id FROM tracks WHERE status='ok' ORDER BY id")

    response = await bob.get(f"/api/radio/{seed}", params={"n": count})

    assert response.status_code == 422


async def test_a_mix_is_one_draw_per_user_and_day_from_its_genre(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, clock: ManualClock
) -> None:
    genre = (await alice.get("/api/genres")).json()[0]["genre"]
    whole = (await alice.get(f"/api/genre/{genre}")).json()["tracks"]

    first, again = [(await alice.get(f"/api/mix/{genre}")).json() for _ in range(2)]

    assert first == again
    assert (first["genre"], first["title"]) == (genre, f"Микс · {genre}")
    assert len(first["tracks"]) == min(50, len(whole))
    assert {item["id"] for item in first["tracks"]} <= {item["id"] for item in whole}
    assert (await bob.get(f"/api/mix/{genre}")).json() != first
    clock.ms += DAY_MS
    assert (await alice.get(f"/api/mix/{genre}")).json() != first
    missing = await alice.get("/api/mix/нетжанра")
    assert (missing.status_code, missing.json()) == (404, {"detail": "no such genre"})


async def test_a_mix_is_kept_for_the_day_under_its_user_key(
    settings: Settings, clock: ManualClock
) -> None:
    cache = MemoryCache()
    application = create_app(
        settings, providers=[ManualClockProvider(clock), MemoryCacheProvider(cache)]
    )
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        alice = await signed_in(application, "alice")
        genre = (await alice.get("/api/genres")).json()[0]["genre"]
        first = (await alice.get(f"/api/mix/{genre}")).json()
        unmixed = first["tracks"][-1]["id"]
        assert (await alice.put(f"/api/likes/{unmixed}", headers=WRITE)).status_code == 204
        again = (await alice.get(f"/api/mix/{genre}")).json()
        await alice.aclose()

    assert again == first == cache.values[f"user:alice:mix:{genre}:{TODAY}"]
    assert cache.ttls[f"user:alice:mix:{genre}:{TODAY}"] == 86400
