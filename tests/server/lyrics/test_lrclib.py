from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from muse.lyrics.domain import LyricsView, UnreachableError
from muse.lyrics.infra.lrclib import Lrclib

type Json = dict[str, Any]

TRACK = "Звезда по имени Солнце"
ARTIST = "Кино"
ALBUM = "Группа крови"
DURATION = 200.0
SYNCED = "[00:01.00]текст"
PLAIN = "текст"
FOUND = {"synced": [{"at": 1.0, "text": "текст"}], "plain": PLAIN, "instrumental": False}
MISSING = {"synced": None, "plain": None, "instrumental": False}


def hit(duration: Any, synced: Any, plain: Any, instrumental: bool = False) -> Json:
    return {
        "id": 1,
        "trackName": TRACK,
        "artistName": ARTIST,
        "albumName": ALBUM,
        "duration": duration,
        "instrumental": instrumental,
        "plainLyrics": plain,
        "syncedLyrics": synced,
    }


@dataclass
class Api:
    exact: httpx.Response | None = None
    found: list[Json] = field(default_factory=list)
    seen: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path == "/api/get":
            return self.exact if self.exact is not None else httpx.Response(404)
        return httpx.Response(200, json=self.found)

    def params(self, path: str) -> dict[str, str]:
        [item] = [request for request in self.seen if request.url.path == path]
        return dict(item.url.params)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.seen]


@pytest.fixture
def api() -> Api:
    return Api()


@pytest.fixture
async def lrclib(api: Api) -> AsyncIterator[Lrclib]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client:
        yield Lrclib(client)


async def find(
    lrclib: Lrclib, duration: float | None = DURATION, album: str | None = ALBUM
) -> LyricsView:
    return await lrclib.find(ARTIST, TRACK, album, duration)


async def test_an_exact_hit_needs_no_search(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, json=hit(DURATION, SYNCED, PLAIN))

    found = await find(lrclib)

    assert found == FOUND
    assert api.paths() == ["/api/get"]
    assert api.params("/api/get") == {
        "artist_name": ARTIST,
        "track_name": TRACK,
        "album_name": ALBUM,
        "duration": "200",
    }


async def test_the_user_agent_names_muse(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, json=hit(DURATION, None, PLAIN))

    await find(lrclib)

    [request] = api.seen
    assert request.headers["user-agent"] == "Muse (https://github.com/tempoloss/Muse)"


async def test_an_absent_album_and_duration_stay_out_of_the_query(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, json=hit(DURATION, None, PLAIN))

    await find(lrclib, album=None, duration=None)

    assert api.params("/api/get") == {"artist_name": ARTIST, "track_name": TRACK}


async def test_a_404_falls_back_to_search_and_takes_a_duration_match(
    api: Api, lrclib: Lrclib
) -> None:
    api.exact = httpx.Response(404)
    api.found = [hit(140.0, "[00:09.00]другая", "другая"), hit(201.0, SYNCED, PLAIN)]

    found = await find(lrclib)

    assert found == FOUND
    assert api.paths() == ["/api/get", "/api/search"]
    assert api.params("/api/search") == {"artist_name": ARTIST, "track_name": TRACK}


async def test_search_prefers_a_candidate_with_synced_lines(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(404)
    api.found = [hit(DURATION, None, PLAIN), hit(DURATION + 1, SYNCED, None)]

    found = await find(lrclib)

    assert found == {"synced": [{"at": 1.0, "text": "текст"}], "plain": None, "instrumental": False}


async def test_search_finds_nothing_without_a_duration_match(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(404)
    api.found = [hit(140.0, SYNCED, PLAIN)]

    assert await find(lrclib) == MISSING


async def test_an_instrumental_hit_says_so(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, json=hit(DURATION, None, None, instrumental=True))

    assert await find(lrclib) == {"synced": None, "plain": None, "instrumental": True}


async def test_a_timeout_is_unreachable() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        with pytest.raises(UnreachableError):
            await Lrclib(client).find(ARTIST, TRACK, ALBUM, DURATION)


async def test_a_server_error_is_unreachable(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(502, text="bad gateway")

    with pytest.raises(UnreachableError):
        await find(lrclib)


async def test_a_rate_limit_is_unreachable_not_a_miss(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(429, text="slow down")

    with pytest.raises(UnreachableError):
        await find(lrclib)

    assert api.paths() == ["/api/get"]


async def test_a_rejected_exact_query_falls_back_to_search(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(400, text="bad request")
    api.found = [hit(DURATION + 1, SYNCED, PLAIN)]

    assert await find(lrclib) == FOUND


async def test_a_server_error_during_the_search_is_unreachable() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(503, text="try later")

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        with pytest.raises(UnreachableError):
            await Lrclib(client).find(ARTIST, TRACK, ALBUM, DURATION)


async def test_a_broken_body_is_unreachable(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, text="not json")

    with pytest.raises(UnreachableError):
        await find(lrclib)


async def test_a_search_body_that_is_not_a_list_is_no_lyrics() -> None:
    def odd(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(200, json={"detail": "nope"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(odd)) as client:
        found = await Lrclib(client).find(ARTIST, TRACK, ALBUM, DURATION)

    assert found == MISSING


async def test_a_candidate_without_a_readable_duration_is_skipped(api: Api, lrclib: Lrclib) -> None:
    junk: list[Any] = ["not a record", hit("200", SYNCED, PLAIN), hit(None, SYNCED, PLAIN)]
    api.exact = httpx.Response(404)
    api.found = junk

    assert await find(lrclib) == MISSING


async def test_an_empty_synced_text_is_no_synced_text(api: Api, lrclib: Lrclib) -> None:
    api.exact = httpx.Response(200, json=hit(DURATION, "", PLAIN))

    assert await find(lrclib) == {"synced": None, "plain": PLAIN, "instrumental": False}
