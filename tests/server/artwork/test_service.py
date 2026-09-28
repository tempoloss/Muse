import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from typing import Any

import pytest
from litestar import Litestar
from structlog.testing import capture_logs

from muse.artwork.domain import ArtworkFiles, ArtworkLibrary, TransientError, artist_key
from muse.artwork.service import Artwork
from muse.catalog.service import Catalog
from muse.settings import Settings
from tests.fixtures.catalog import (
    COVER_ALBUM,
    COVER_ARTIST,
    DRIFTED_CANONICAL,
    RENAMED_CANONICAL,
    RENAMED_TAG,
    FixtureCatalog,
)
from tests.server.artwork.fakes import FakeStores, Pauses

ART = "https://cdn.example.org/art.jpg"
FACE = "https://cdn.example.org/face.jpg"


def query(library: FixtureCatalog, sql: str, *params: object) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(library.catalog_db)) as db:
        return db.execute(sql, params).fetchall()


def album_named(library: FixtureCatalog, name: str) -> int:
    return query(library, "SELECT id FROM albums WHERE name=?", name)[0][0]


def renamed_album(library: FixtureCatalog) -> tuple[int, str, tuple[str, ...]]:
    album_id, name = query(library, "SELECT id, name FROM albums WHERE artist=?", RENAMED_TAG)[0]
    tracks = query(library, "SELECT num, title, status FROM tracks WHERE album_id=?", album_id)
    return album_id, name, tuple(title for _, title, status in sorted(tracks) if status == "ok")


def two_album_artist(library: FixtureCatalog) -> tuple[str, int, int]:
    albums: defaultdict[str, Counter[int]] = defaultdict(Counter)
    rows = query(
        library,
        "SELECT COALESCE(ar.canonical, t.artist), t.album_id FROM tracks t "
        "LEFT JOIN artists ar ON ar.name=t.artist WHERE t.status='ok'",
    )
    for artist, album_id in rows:
        albums[artist][album_id] += 1
    for artist in sorted(albums):
        (big, big_size), *rest = albums[artist].most_common()
        if len(rest) == 1 and rest[0][1] < big_size:
            return artist, big, rest[0][0]
    raise AssertionError("the fixture has no artist with two albums of different sizes")


@pytest.fixture
def stores() -> FakeStores:
    return FakeStores()


@pytest.fixture
def pauses() -> Pauses:
    return Pauses()


@pytest.fixture
async def artwork(app: Litestar, stores: FakeStores, pauses: Pauses) -> Artwork:
    container = app.state.dishka_container
    return Artwork(
        await container.get(Catalog),
        await container.get(ArtworkLibrary),
        await container.get(ArtworkFiles),
        stores,
        pauses,
    )


async def test_online_an_album_without_a_picture_gets_its_store_cover(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog
) -> None:
    album_id, name, titles = renamed_album(library)
    stores.covers[name] = ART
    stores.images[ART] = b"store cover"

    found = await artwork.cover_file(album_id, online=True)

    assert found is not None
    assert found.read_bytes() == b"store cover"
    assert stores.asked == [((DRIFTED_CANONICAL, RENAMED_TAG), name, titles)]
    assert await artwork.cover_file(album_id) == found


async def test_online_an_album_no_store_knows_is_remembered_as_missing(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog, settings: Settings
) -> None:
    album_id, name, _ = renamed_album(library)

    first = await artwork.cover_file(album_id, online=True)
    stores.covers[name] = ART
    again = await artwork.cover_file(album_id, online=True)

    assert (first, again) == (None, None)
    assert (settings.paths.covers_dir / f"{album_id}.none").is_file()
    assert len(stores.asked) == 1


async def test_online_a_store_failure_is_raised_and_not_remembered(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog, settings: Settings
) -> None:
    album_id, name, _ = renamed_album(library)
    stores.failures[name] = 1

    with pytest.raises(TransientError):
        await artwork.cover_file(album_id, online=True)

    assert not (settings.paths.covers_dir / f"{album_id}.none").exists()


async def test_an_embedded_picture_is_used_before_any_store(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog
) -> None:
    found = await artwork.cover_file(album_named(library, COVER_ALBUM), online=True)

    assert found is not None
    assert found.read_bytes() == library.cover_jpeg
    assert stores.asked == []


async def test_an_artist_without_a_store_picture_gets_the_cover_of_their_biggest_album(
    artwork: Artwork, library: FixtureCatalog, settings: Settings
) -> None:
    name, big, small = two_album_artist(library)
    covers = settings.paths.covers_dir
    covers.mkdir(parents=True)
    (covers / f"{big}.jpg").write_bytes(b"big album")
    (covers / f"{small}.jpg").write_bytes(b"small album")
    image = settings.paths.artists_dir / f"{artist_key(name)}.jpg"

    first = await artwork.find_artist_image(name)
    biggest = image.read_bytes()
    image.unlink()
    (covers / f"{big}.jpg").unlink()
    second = await artwork.find_artist_image(name)

    assert (first, biggest) == ("cover", b"big album")
    assert (second, image.read_bytes()) == ("cover", b"small album")


async def test_a_store_picture_beats_album_covers(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog, settings: Settings
) -> None:
    name, big, _ = two_album_artist(library)
    settings.paths.covers_dir.mkdir(parents=True)
    (settings.paths.covers_dir / f"{big}.jpg").write_bytes(b"big album")
    stores.pictures[name] = FACE
    stores.images[FACE] = b"face"

    source = await artwork.find_artist_image(name)

    assert source == "deezer"
    assert (settings.paths.artists_dir / f"{artist_key(name)}.jpg").read_bytes() == b"face"


async def test_a_store_failure_without_covers_is_retried_later_and_a_plain_miss_is_kept(
    artwork: Artwork, stores: FakeStores, library: FixtureCatalog, settings: Settings
) -> None:
    name, _, _ = two_album_artist(library)
    miss = settings.paths.artists_dir / f"{artist_key(name)}.none"
    stores.failures[name] = 1

    with pytest.raises(TransientError):
        await artwork.find_artist_image(name)
    failed_leaves_no_mark = not miss.exists()
    plain = await artwork.find_artist_image(name)
    stores.pictures[name] = FACE
    later = await artwork.find_artist_image(name)

    assert failed_leaves_no_mark
    assert (plain, later) == ("none", None)
    assert miss.is_file()


async def test_the_warmer_retries_store_failures_with_doubling_waits_up_to_half_an_hour(
    artwork: Artwork,
    stores: FakeStores,
    pauses: Pauses,
    library: FixtureCatalog,
    settings: Settings,
) -> None:
    covers, artists = settings.paths.covers_dir, settings.paths.artists_dir
    covered, (flaky, flaky_name, _) = album_named(library, COVER_ALBUM), renamed_album(library)
    plain = next(row[0] for row in query(library, "SELECT id FROM albums ORDER BY id"))
    covers.mkdir(parents=True)
    for (album_id,) in query(library, "SELECT id FROM albums"):
        if album_id not in (covered, flaky, plain):
            (covers / f"{album_id}.none").touch()
    names = [artist["name"] for artist in await artwork.catalog.artists()]
    pictured, unknown = [n for n in names if n not in (COVER_ARTIST, RENAMED_CANONICAL)][:2]
    artists.mkdir(parents=True)
    for name in names:
        if name not in (pictured, unknown):
            (artists / f"{artist_key(name)}.none").touch()
    stores.covers[flaky_name] = ART
    stores.images.update({ART: b"store cover", FACE: b"face"})
    stores.pictures[pictured] = FACE
    stores.failures.update({flaky_name: 7, unknown: 2})

    with capture_logs() as logs:
        await artwork.warm()

    assert pauses == [60, 120, 240, 480, 960, 1800, 1800, 60, 120]
    assert [entry["event"] for entry in logs] == [
        *(
            f"covers: 1 albums hit store errors (last: quota); retry in {wait}s"
            for wait in (60, 120, 240, 480, 960, 1800, 1800)
        ),
        "covers: warmed 2/3",
        "artists: 1 hit store errors (last: quota); retry in 60s",
        "artists: 1 hit store errors (last: quota); retry in 120s",
        "artists: warmed 1 deezer, 0 cover, 1 none / 2",
    ]
    assert (covers / f"{covered}.jpg").read_bytes() == library.cover_jpeg
    assert (covers / f"{flaky}.jpg").read_bytes() == b"store cover"
    assert (covers / f"{plain}.none").is_file()
    assert (artists / f"{artist_key(pictured)}.jpg").read_bytes() == b"face"
    assert (artists / f"{artist_key(unknown)}.none").is_file()
