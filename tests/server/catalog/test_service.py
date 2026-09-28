import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from litestar import Litestar

from muse.catalog.domain import LibraryRoot
from muse.catalog.infra.files import TrackFiles
from muse.catalog.infra.library import LibraryFiles
from muse.catalog.infra.playlists import PlaylistFiles
from muse.catalog.infra.sql import SqlCatalog
from muse.catalog.service import Catalog
from muse.settings import Settings
from muse.shared.db import CatalogDb, catalog_engine
from muse.shared.errors import DomainError
from tests.fixtures.catalog import UNTIMED_ARTIST, FixtureCatalog
from tests.server.catalog.support import fixture_rows

TRACK_KEYS = {"id", "num", "title", "dur", "album_id", "album", "artist"}


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


@pytest.fixture
async def catalog(app: Litestar) -> Catalog:
    return await app.state.dishka_container.get(Catalog)


def ok_ids(library: FixtureCatalog, limit: int) -> list[int]:
    rows = fixture_rows(
        library, "SELECT id FROM tracks WHERE status='ok' ORDER BY id LIMIT ?", (limit,)
    )
    return [row["id"] for row in rows]


async def test_track_rows_cover_only_playable_tracks(
    catalog: Catalog, library: FixtureCatalog
) -> None:
    first, second = ok_ids(library, 2)
    pending = fixture_rows(library, "SELECT id FROM tracks WHERE status<>'ok' LIMIT 1")[0]["id"]

    rows = await catalog.track_rows([second, first, second, pending, 999999])
    ordered = await catalog.tracks_in_order([second, pending, first, 999999])

    assert set(rows) == {first, second}
    assert set(rows[first]) == TRACK_KEYS
    assert [t["id"] for t in ordered] == [second, first]
    assert await catalog.track_rows([]) == {}


async def test_playable_duration_treats_a_missing_length_as_zero(
    catalog: Catalog, library: FixtureCatalog
) -> None:
    untimed = fixture_rows(
        library, "SELECT id FROM tracks WHERE artist=? AND dur IS NULL", (UNTIMED_ARTIST,)
    )[0]["id"]
    timed = fixture_rows(library, "SELECT id, dur FROM tracks WHERE status='ok' AND dur>60")[0]
    pending = fixture_rows(library, "SELECT id FROM tracks WHERE status='pending'")[0]["id"]

    assert await catalog.playable_duration(untimed) == 0
    assert await catalog.playable_duration(timed["id"]) == timed["dur"]
    with pytest.raises(DomainError, match="no track"):
        await catalog.playable_duration(pending)


async def test_album_heads_exist_only_for_albums_with_playable_tracks(
    catalog: Catalog, library: FixtureCatalog
) -> None:
    album_id = fixture_rows(library, "SELECT album_id FROM tracks WHERE status='ok'")[0]["album_id"]

    head = await catalog.album_head(album_id)

    assert head is not None
    assert set(head) == {"id", "name", "artist"}
    assert await catalog.album_head(999999) is None


async def test_cover_mosaics_take_the_first_four_covered_albums(
    catalog: Catalog, settings: Settings
) -> None:
    tracks = [{"album_id": album_id} for album_id in (5, 3, 5, 9, 1, 7, 2)]
    settings.paths.covers_dir.mkdir()
    for album_id in (3, 9, 1, 7, 2):
        (settings.paths.covers_dir / f"{album_id}.jpg").write_bytes(b"jpg")

    assert await catalog.cover_ids(tracks) == [3, 9, 1, 7]
    assert await catalog.cover_ids(tracks, limit=2) == [3, 9]


async def test_cached_listings_are_keyed_by_the_library_fingerprint(
    library: FixtureCatalog, tmp_path: Path
) -> None:
    database = tmp_path / "state.sqlite"
    shutil.copyfile(library.catalog_db, database)
    playlists = tmp_path / "_Playlists"
    playlists.mkdir()
    cache = CountingCache()
    catalog = Catalog(
        SqlCatalog(CatalogDb(catalog_engine(database))),
        LibraryFiles(database, playlists, tmp_path / "covers"),
        PlaylistFiles(playlists),
        TrackFiles(library.library_dir, LibraryRoot.at(library.library_dir)),
        LibraryRoot.at(library.library_dir),
        cache,
    )

    first = await catalog.genres()
    await catalog.genres()
    (playlists / "New.m3u8").write_text("", encoding="utf-8")
    await catalog.genres()
    stat = database.stat()
    os.utime(database, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    await catalog.genres()

    assert first == cache.values[cache.computed[0]]
    assert len(cache.computed) == 3
    assert all(key.startswith("lib:") and key.endswith(":genres") for key in cache.computed)
