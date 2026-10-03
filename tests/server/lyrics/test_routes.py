from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest
from dishka import Provider, Scope, provide
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.catalog.service import Catalog
from muse.lyrics.domain import LyricsSource, LyricsView, UnreachableError
from muse.lyrics.service import Lyrics
from muse.settings import Settings
from muse.shared.cache import NullCache
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, signed_in

FOUND: LyricsView = {
    "synced": [{"at": 12.34, "text": "слушай"}, {"at": 20.0, "text": ""}],
    "plain": "слушай",
    "instrumental": False,
}


@dataclass
class FakeSource:
    answer: LyricsView = field(default_factory=lambda: FOUND)
    error: Exception | None = None
    calls: int = 0

    async def find(
        self, artist: str, title: str, album: str | None, duration: float | None
    ) -> LyricsView:
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer


class SourceProvider(Provider):
    def __init__(self, source: FakeSource) -> None:
        super().__init__()
        self._source = source

    @provide(scope=Scope.APP)
    def source(self) -> LyricsSource:
        return self._source

    @provide(scope=Scope.APP)
    async def lyrics(self, catalog: Catalog) -> Lyrics:
        return Lyrics(catalog, self._source, NullCache())


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
async def app(settings: Settings, source: FakeSource) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[SourceProvider(source)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


@pytest.fixture
async def alice(app: Litestar) -> AsyncIterator[httpx.AsyncClient]:
    client = await signed_in(app, "alice")
    yield client
    await client.aclose()


@pytest.fixture
def track_id(library: FixtureCatalog) -> int:
    [row] = fixture_rows(
        library, "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 1"
    )
    return int(row["id"])


async def test_a_track_with_lyrics_answers_the_view_shape(
    alice: httpx.AsyncClient, source: FakeSource, track_id: int
) -> None:
    response = await alice.get(f"/api/lyrics/{track_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "synced": [{"at": 12.34, "text": "слушай"}, {"at": 20.0, "text": ""}],
        "plain": "слушай",
        "instrumental": False,
    }
    assert source.calls == 1


async def test_a_track_lrclib_does_not_know_answers_empty(
    alice: httpx.AsyncClient, source: FakeSource, track_id: int
) -> None:
    source.answer = {"synced": None, "plain": None, "instrumental": False}

    response = await alice.get(f"/api/lyrics/{track_id}")

    assert (response.status_code, response.json()) == (
        200,
        {"synced": None, "plain": None, "instrumental": False},
    )


async def test_lyrics_need_a_session(client: httpx.AsyncClient, track_id: int) -> None:
    response = await client.get(f"/api/lyrics/{track_id}")

    assert response.status_code == 401


async def test_an_unknown_track_is_404_no_track(alice: httpx.AsyncClient) -> None:
    response = await alice.get("/api/lyrics/999999")

    assert (response.status_code, response.json()) == (404, {"detail": "no track"})


async def test_a_dead_lrclib_is_503_and_is_asked_again(
    alice: httpx.AsyncClient, source: FakeSource, track_id: int
) -> None:
    source.error = UnreachableError()

    first = await alice.get(f"/api/lyrics/{track_id}")
    second = await alice.get(f"/api/lyrics/{track_id}")

    assert (first.status_code, first.json()) == (503, {"detail": "lyrics unavailable"})
    assert second.status_code == 503
    assert source.calls == 2
