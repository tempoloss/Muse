from pathlib import Path

import anyio
import httpx
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.catalog.domain import LibraryRoot
from muse.catalog.infra.files import TrackFiles
from muse.settings import Settings
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, signed_in


def track_where(library: FixtureCatalog, condition: str) -> tuple[int, str]:
    row = fixture_rows(library, f"SELECT id, path FROM tracks WHERE {condition} LIMIT 1")[0]
    return row["id"], row["path"]


async def test_streaming_needs_a_session(
    client: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    track_id, _ = track_where(library, "status='ok'")

    assert (await client.get(f"/api/stream/{track_id}")).status_code == 401


async def test_a_track_streams_byte_ranges_for_scrubbing(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    track_id, stored = track_where(library, "status='ok' AND path LIKE '%lib%'")
    relative_id, relative = track_where(
        library, "status='ok' AND path NOT LIKE '%:%' AND path NOT LIKE '/%'"
    )
    body = await anyio.Path(stored).read_bytes()

    part = await alice.get(f"/api/stream/{track_id}", headers={"Range": "bytes=0-1023"})
    whole = await alice.get(f"/api/stream/{relative_id}")

    assert (part.status_code, part.content) == (206, body[:1024])
    assert part.headers["content-range"] == f"bytes 0-1023/{len(body)}"
    assert part.headers["cache-control"] == "private, max-age=86400"
    assert part.headers["content-type"] == "audio/mpeg"
    assert whole.status_code == 200
    assert whole.content == await anyio.Path(library.library_dir / relative).read_bytes()


async def test_unplayable_and_missing_tracks_are_404(
    alice: httpx.AsyncClient, library: FixtureCatalog, settings: Settings, tmp_path: Path
) -> None:
    pending, _ = track_where(library, "status='pending'")
    playable, _ = track_where(library, "status='ok'")
    empty = tmp_path / "empty-library"
    empty.mkdir()
    moved = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"library_dir": empty})}
    )

    missing = await alice.get(f"/api/stream/{pending}")
    application = create_app(moved)
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        client = await signed_in(application, "alice")
        gone = await client.get(f"/api/stream/{playable}")
        await client.aclose()

    assert (missing.status_code, missing.json()) == (404, {"detail": "no track"})
    assert (gone.status_code, gone.json()) == (404, {"detail": "file gone"})
    assert gone.headers["cache-control"] == "no-store"


def test_stored_paths_find_files_only_inside_the_library(tmp_path: Path) -> None:
    library = tmp_path / "Music Lib"
    track = library / "Indie" / "Band" / "01 - Song.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"mp3")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    files = TrackFiles(library, LibraryRoot.at(library))
    shouted = (tmp_path / "MUSIC LIB").as_posix().replace("/", "\\")
    windows_style = shouted + "\\Indie\\Band\\01 - Song.mp3"

    assert files.locate("Indie/Band/01 - Song.mp3") == track
    assert files.locate(windows_style) == track
    assert files.locate("Indie/Band/02 - Missing.mp3") is None
    assert files.locate("Indie/../../secret.txt") is None
    assert files.locate((tmp_path / "secret.txt").as_posix()) is None
    assert files.locate(None) is None
