from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from litestar import Litestar

from muse.catalog.service import Catalog
from muse.lyrics.domain import LyricsView, UnreachableError
from muse.lyrics.service import Lyrics
from muse.shared.errors import DomainError
from tests.fixtures.catalog import SINGLES_ALBUM, UNTIMED_ARTIST, FixtureCatalog
from tests.server.catalog.support import fixture_rows

FOUND: LyricsView = {
    "synced": [{"at": 1.0, "text": "текст"}],
    "plain": "текст",
    "instrumental": False,
}
MISSING: LyricsView = {"synced": None, "plain": None, "instrumental": False}


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


@dataclass
class FakeSource:
    answer: LyricsView = field(default_factory=lambda: FOUND)
    error: Exception | None = None
    asked: list[tuple[str, str, str | None, float | None]] = field(default_factory=list)

    async def find(
        self, artist: str, title: str, album: str | None, duration: float | None
    ) -> LyricsView:
        self.asked.append((artist, title, album, duration))
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def cache() -> CountingCache:
    return CountingCache()


@pytest.fixture
async def catalog(app: Litestar) -> Catalog:
    return await app.state.dishka_container.get(Catalog)


@pytest.fixture
async def lyrics(catalog: Catalog, source: FakeSource, cache: CountingCache) -> Lyrics:
    return Lyrics(catalog, source, cache)


def playable(library: FixtureCatalog, sql: str) -> int:
    [row] = fixture_rows(library, sql)
    return int(row["id"])


@pytest.fixture
def track_id(library: FixtureCatalog) -> int:
    return playable(
        library, "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 1"
    )


async def test_the_lookup_asks_with_catalog_metadata(
    lyrics: Lyrics, source: FakeSource, catalog: Catalog, track_id: int
) -> None:
    track = await catalog.track(track_id)

    assert await lyrics.for_track(track_id) == FOUND
    assert source.asked == [
        (track["artist"], track["title"], track["album"], float(track["dur"] or 0))
    ]


async def test_a_single_is_looked_up_without_its_bucket_album(
    lyrics: Lyrics, source: FakeSource, catalog: Catalog, library: FixtureCatalog
) -> None:
    single = playable(
        library, f"SELECT id FROM tracks WHERE status='ok' AND album='{SINGLES_ALBUM}' LIMIT 1"
    )
    track = await catalog.track(single)

    await lyrics.for_track(single)

    [(_artist, _title, album, _duration)] = source.asked
    assert track["album"].startswith("Синглы · ")
    assert album is None


async def test_a_track_without_a_duration_is_looked_up_anyway(
    lyrics: Lyrics, source: FakeSource, library: FixtureCatalog
) -> None:
    untimed = playable(
        library,
        f"SELECT id FROM tracks WHERE status='ok' AND artist='{UNTIMED_ARTIST}' AND dur IS NULL LIMIT 1",
    )

    await lyrics.for_track(untimed)

    [(_artist, _title, _album, duration)] = source.asked
    assert duration is None


async def test_an_unknown_track_is_a_catalog_404(lyrics: Lyrics, source: FakeSource) -> None:
    with pytest.raises(DomainError) as raised:
        await lyrics.for_track(999_999)

    assert raised.value.code == "no track"
    assert source.asked == []


async def test_a_successful_lookup_is_computed_once_per_track(
    lyrics: Lyrics, source: FakeSource, cache: CountingCache, track_id: int
) -> None:
    await lyrics.for_track(track_id)
    await lyrics.for_track(track_id)

    assert len(source.asked) == 1
    assert cache.computed == [f"lyrics:{track_id}"]


async def test_a_missing_answer_is_cached_too(
    lyrics: Lyrics, source: FakeSource, track_id: int
) -> None:
    source.answer = MISSING

    assert await lyrics.for_track(track_id) == MISSING
    await lyrics.for_track(track_id)

    assert len(source.asked) == 1


async def test_an_unreachable_source_is_never_cached(
    lyrics: Lyrics, source: FakeSource, cache: CountingCache, track_id: int
) -> None:
    source.error = UnreachableError()

    for _ in range(2):
        with pytest.raises(UnreachableError):
            await lyrics.for_track(track_id)

    assert len(source.asked) == 2
    assert cache.values == {}
