import io
import sqlite3
from contextlib import closing

import httpx
import pytest
from PIL import Image

from muse.artwork.domain import artist_key
from muse.settings import Settings
from tests.fixtures.catalog import COVER_ALBUM, COVER_ARTIST, FixtureCatalog

WEEK = "private, max-age=604800"


def cover_album(library: FixtureCatalog) -> int:
    with closing(sqlite3.connect(library.catalog_db)) as db:
        return db.execute("SELECT id FROM albums WHERE name=?", (COVER_ALBUM,)).fetchone()[0]


def jpeg(side: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (30, 90, 150)).save(buffer, "JPEG")
    return buffer.getvalue()


def image_size(response: httpx.Response) -> tuple[int, int]:
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format == "JPEG"
        return image.size


async def test_a_cover_is_the_embedded_picture_kept_privately_for_a_week(
    client: httpx.AsyncClient,
    alice: httpx.AsyncClient,
    library: FixtureCatalog,
    settings: Settings,
) -> None:
    album_id = cover_album(library)

    anonymous = await client.get(f"/api/cover/{album_id}")
    response = await alice.get(f"/api/cover/{album_id}")

    assert anonymous.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == WEEK
    assert response.content == library.cover_jpeg
    assert (settings.paths.covers_dir / f"{album_id}.jpg").read_bytes() == library.cover_jpeg


@pytest.mark.parametrize("size", [128, 384])
async def test_list_sizes_get_a_cover_thumbnail(
    alice: httpx.AsyncClient, library: FixtureCatalog, size: int
) -> None:
    response = await alice.get(f"/api/cover/{cover_album(library)}", params={"s": size})

    assert image_size(response) == (size, size)


async def test_other_sizes_get_the_original_cover(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    response = await alice.get(f"/api/cover/{cover_album(library)}", params={"s": 200})

    assert response.content == library.cover_jpeg


async def test_no_picture_a_known_miss_or_an_unknown_album_is_no_cover(
    alice: httpx.AsyncClient, library: FixtureCatalog, settings: Settings
) -> None:
    covered = cover_album(library)
    covers = settings.paths.covers_dir
    covers.mkdir(parents=True)
    (covers / f"{covered}.none").touch()

    responses = [await alice.get(f"/api/cover/{album_id}") for album_id in (1, covered, 999_999)]

    for response in responses:
        assert (response.status_code, response.json()) == (404, {"detail": "no cover"})
        assert response.headers["cache-control"] == "no-store"
    assert [path.name for path in covers.iterdir()] == [f"{covered}.none"]


async def test_an_artist_image_is_served_only_once_it_is_cached(
    alice: httpx.AsyncClient, settings: Settings
) -> None:
    missing = await alice.get("/api/artist-image", params={"name": COVER_ARTIST})
    settings.paths.artists_dir.mkdir(parents=True)
    picture = jpeg(500)
    (settings.paths.artists_dir / f"{artist_key(COVER_ARTIST)}.jpg").write_bytes(picture)

    found = await alice.get("/api/artist-image", params={"name": COVER_ARTIST})
    small = await alice.get("/api/artist-image", params={"name": COVER_ARTIST, "s": 128})

    assert (missing.status_code, missing.json()) == (404, {"detail": "no artist image"})
    assert (found.status_code, found.content) == (200, picture)
    assert found.headers["cache-control"] == WEEK
    assert image_size(small) == (128, 128)
