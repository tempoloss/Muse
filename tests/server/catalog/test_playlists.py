from pathlib import PureWindowsPath
from urllib.parse import quote

import httpx
import pytest
from litestar import Litestar

from muse.catalog.domain import LibraryRoot
from muse.catalog.service import Catalog
from muse.settings import Settings
from tests.fixtures.catalog import PLAYLISTS, FixtureCatalog
from tests.server.catalog.support import fixture_rows, identity

TRACK_KEYS = {"id", "num", "title", "dur", "album_id", "album", "artist"}


def albums_in_order(library: FixtureCatalog, ids: tuple[int, ...]) -> list[int]:
    album_of = {
        row["id"]: row["album_id"]
        for row in fixture_rows(library, "SELECT id, album_id FROM tracks")
    }
    return list(dict.fromkeys(album_of[track_id] for track_id in ids))


async def test_playlists_list_their_playable_tracks_and_cover_mosaic(
    alice: httpx.AsyncClient, library: FixtureCatalog, settings: Settings
) -> None:
    durations = {
        row["id"]: row["dur"] or 0 for row in fixture_rows(library, "SELECT id, dur FROM tracks")
    }
    settings.paths.covers_dir.mkdir()
    for row in fixture_rows(library, "SELECT DISTINCT album_id FROM tracks"):
        (settings.paths.covers_dir / f"{row['album_id']}.jpg").write_bytes(b"jpg")

    listed = (await alice.get("/api/playlists")).json()

    assert [p["name"] for p in listed] == list(PLAYLISTS)
    for entry in listed:
        ids = library.playlists[entry["name"]]
        assert (entry["tracks"], entry["dur"]) == (len(ids), sum(durations[i] for i in ids))
        assert entry["albums"] == albums_in_order(library, ids)[:4]


async def test_a_playlist_resolves_device_paths_case_insensitively_in_order(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    for name in PLAYLISTS:
        page = (await alice.get(f"/api/playlist/{quote(name)}")).json()

        assert page["name"] == name
        assert [t["id"] for t in page["tracks"]] == list(library.playlists[name])
        assert set(page["tracks"][0]) == TRACK_KEYS
        assert page["albums"] == []


@pytest.mark.parametrize("name", ["Nope", "Archive", "x\\Mix", "..%2FMix"])
async def test_only_m3u8_files_inside_the_playlist_folder_exist(
    alice: httpx.AsyncClient, name: str
) -> None:
    response = await alice.get(f"/api/playlist/{quote(name, safe='%')}")

    assert response.status_code == 404
    assert "tracks" not in response.json()


async def test_playlist_artists_follow_the_playlist_files(
    app: Litestar, library: FixtureCatalog
) -> None:
    catalog = await app.state.dishka_container.get(Catalog)
    names = identity(library)
    artist_of = {
        row["id"]: names[row["artist"]]
        for row in fixture_rows(library, "SELECT id, artist FROM tracks")
    }

    sets = await catalog.playlist_artists()

    assert sets == [{artist_of[i] for i in library.playlists[name]} for name in PLAYLISTS]
    assert await catalog.has_playlist("Mix")
    assert not await catalog.has_playlist("Archive")


@pytest.mark.parametrize(
    ("stored", "relative"),
    [
        ("Rap/A/B/01 - x.mp3", "Rap/A/B/01 - x.mp3"),
        ("D:\\music\\lib\\Rap\\A\\01 - x.mp3", "Rap/A/01 - x.mp3"),
        ("d:/MUSIC/Lib/Rap/A/01 - x.mp3", "Rap/A/01 - x.mp3"),
        ("D:/music/library/Rap/x.mp3", None),
        ("/etc/passwd", None),
        ("Indie/../../etc/passwd", None),
        ("", None),
        (None, None),
    ],
)
def test_stored_paths_resolve_only_inside_the_library(
    stored: str | None, relative: str | None
) -> None:
    root = LibraryRoot.at(PureWindowsPath("D:/music/lib"))

    assert root.relative(stored) == relative
    assert root.key(stored) == (relative.casefold() if relative else None)
