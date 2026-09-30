import itertools
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import closing
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
from tests.server.support import ORIGIN, WRITE, signed_in


class CountingCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.computed: list[str] = []

    async def get_or_compute[T](self, key: str, ttl: int, compute: Callable[[], Awaitable[T]]) -> T:
        if key not in self.values:
            self.computed.append(key)
            self.values[key] = await compute()
        return self.values[key]

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)


class CacheProvider(Provider):
    def __init__(self, cache: CountingCache) -> None:
        super().__init__()
        self._cache = cache

    @provide(scope=Scope.APP)
    def cache(self) -> Cache:
        return self._cache


def ok_track(library: FixtureCatalog, condition: str = "dur>60") -> dict[str, Any]:
    row = fixture_rows(
        library, f"SELECT id, dur, album_id FROM tracks WHERE status='ok' AND {condition} LIMIT 1"
    )[0]
    return dict(row)


STARTS = itertools.count(int(time.time() * 1000))


async def play(
    client: httpx.AsyncClient, track_id: int, listened_ms: int, source: str = "other"
) -> None:
    response = await client.post(
        "/api/plays",
        headers=WRITE,
        json={
            "track_id": track_id,
            "started_at": next(STARTS),
            "listened_ms": listened_ms,
            "completed": False,
            "skipped": False,
            "source": source,
        },
    )
    assert response.status_code == 204, response.text


async def home(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/home")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_heard_track_shows_up_as_recent_even_before_it_counts(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    track = ok_track(library)

    await play(bob, track["id"], 10000)

    assert track["id"] in [t["id"] for t in (await home(bob))["recent"]]
    assert track["id"] in [t["id"] for t in (await home(alice))["partner_recent"]]


async def test_songs_both_like_appear_for_both_until_one_unlikes(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    track = ok_track(library)
    for client in (alice, bob):
        assert (await client.put(f"/api/likes/{track['id']}", headers=WRITE)).status_code == 204
    for client in (alice, bob):
        assert track["id"] in [t["id"] for t in (await home(client))["both_like"]]

    assert (await bob.delete(f"/api/likes/{track['id']}", headers=WRITE)).status_code == 204

    for client in (alice, bob):
        assert track["id"] not in [t["id"] for t in (await home(client))["both_like"]]


async def test_continue_starts_with_the_last_album(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    track = ok_track(library)

    await play(alice, track["id"], 40000, source=f"album:{track['album_id']}")

    first = (await home(alice))["continue"][0]
    assert (first["kind"], first["album_id"], first["albums"]) == (
        "album",
        track["album_id"],
        [track["album_id"]],
    )


async def test_continue_offers_the_genre_ours_and_daily_cards(
    alice: httpx.AsyncClient, settings: Settings, library: FixtureCatalog
) -> None:
    track = ok_track(library)
    genre = (await alice.get("/api/genres")).json()[0]["genre"]
    assert (await alice.put(f"/api/ours/{track['id']}", headers=WRITE)).status_code == 204
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        cursor = db.execute(
            "INSERT INTO daily(day, slot, for_user, title, blurb, tracks, model, created_at) "
            "VALUES ('2026-01-15', 0, 'alice', 'Утро', 'бодро', ?, 'm', 1)",
            (json.dumps([track["id"]]),),
        )
        daily_id = cursor.lastrowid
        db.commit()

    await play(alice, track["id"], 40000, source=f"genre:{genre}")
    await play(alice, track["id"], 40000, source="ours")
    await play(alice, track["id"], 40000, source=f"daily:{daily_id}")
    await play(alice, track["id"], 40000, source="daily:999999")
    await play(alice, track["id"], 40000, source="mix:нетжанра")

    cards = (await home(alice))["continue"]
    assert [card["kind"] for card in cards] == ["daily", "ours", "genre"]
    assert cards[0]["id"] == daily_id
    assert cards[2]["genre"] == genre


async def test_mixes_follow_listening_then_genre_size_without_other(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    genres = [g["genre"] for g in (await alice.get("/api/genres")).json()]
    smallest = next(g for g in reversed(genres) if g != "Other")
    track = fixture_rows(
        library,
        "SELECT t.id FROM tracks t JOIN albums a ON a.id=t.album_id "
        "WHERE t.status='ok' AND t.dur>60 AND a.genre=? LIMIT 1",
        (smallest,),
    )[0]["id"]

    await play(alice, track, 40000)

    mixes = (await home(alice))["mixes"]
    assert [m["genre"] for m in mixes] == [
        smallest,
        *[g for g in genres if g not in ("Other", smallest)],
    ]
    assert all(m["title"] == f"Микс · {m['genre']}" for m in mixes)


async def test_forgotten_albums_are_unheard_albums_with_three_tracks(
    alice: httpx.AsyncClient,
) -> None:
    albums = {a["id"]: a for a in (await alice.get("/api/albums")).json()}

    forgotten = (await home(alice))["forgotten"]

    assert 0 < len(forgotten) <= 10
    assert all(albums[a["id"]]["ntracks"] >= 3 for a in forgotten)
    assert forgotten == (await home(alice))["forgotten"]


@pytest.fixture
async def counted(settings: Settings) -> AsyncIterator[tuple[Litestar, CountingCache]]:
    cache = CountingCache()
    application = create_app(settings, providers=[CacheProvider(cache)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application, cache


async def test_the_home_is_cached_until_a_play_like_or_shared_track_changes_it(
    counted: tuple[Litestar, CountingCache], library: FixtureCatalog
) -> None:
    application, cache = counted
    alice = await signed_in(application, "alice")
    bob = await signed_in(application, "bob")
    track = ok_track(library)

    await home(alice)
    await home(alice)
    await home(bob)
    homes = [key for key in cache.computed if ":home:" in key]
    assert len(homes) == 2

    for change in (
        lambda: alice.put(f"/api/likes/{track['id']}", headers=WRITE),
        lambda: bob.put(f"/api/ours/{track['id']}", headers=WRITE),
    ):
        assert (await change()).status_code == 204
        before = len([key for key in cache.computed if ":home:" in key])
        await home(alice)
        await home(bob)
        assert len([key for key in cache.computed if ":home:" in key]) == before + 2

    await play(bob, track["id"], 40000)
    assert not [key for key in cache.values if ":home:" in key]
    await alice.aclose()
    await bob.aclose()
