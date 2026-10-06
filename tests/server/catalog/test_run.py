import shutil
from pathlib import Path

import httpx
import pytest
from litestar.testing import AsyncTestClient
from structlog.testing import capture_logs

from muse.app import create_app
from muse.catalog.domain import LibraryRoot
from muse.catalog.infra.files import TrackFiles, reencode
from muse.catalog.infra.library import LibraryFiles
from muse.catalog.infra.playlists import PlaylistFiles
from muse.catalog.infra.sql import SqlCatalog
from muse.catalog.service import Catalog
from muse.settings import Settings
from muse.shared.cache import NullCache
from muse.shared.db import CatalogDb, catalog_engine
from muse.shared.mp3 import STREAM_KIND, FrameReader, frame_at, silent_frame
from tests.fixtures.audio import mp3_bytes
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, signed_in

PER_SECOND = STREAM_KIND.rate / STREAM_KIND.samples
MONO_44_FRAME = bytes.fromhex("fffb90c4") + bytes(413)
ENCODED_FRAME = bytes.fromhex("fffb9404") + b"\x07" * 380


def storage(library: Path) -> TrackFiles:
    return TrackFiles(library, LibraryRoot.at(library))


def playable(
    library: FixtureCatalog, count: int, within: Path | None = None
) -> list[tuple[int, int, Path]]:
    files = storage(within or library.library_dir)
    found: list[tuple[int, int, Path]] = []
    sql = "SELECT id, dur, path FROM tracks WHERE status='ok' AND dur > 0 ORDER BY id"
    for row in fixture_rows(library, sql):
        path = files.locate(row["path"])
        if path is not None:
            found.append((row["id"], row["dur"], path))
        if len(found) == count:
            break
    return found


def frames_of(stream: bytes) -> list[bytes]:
    frames, at = [], 0
    while at < len(stream):
        found = frame_at(stream, at)
        assert found is not None, f"no frame at byte {at}"
        assert found[0] == STREAM_KIND
        frames.append(stream[at : at + found[1]])
        at += found[1]
    return frames


def copied(library: FixtureCatalog, tmp_path: Path) -> Path:
    copy = tmp_path / "lib"
    shutil.copytree(library.library_dir, copy)
    return copy


def other_format(
    library: FixtureCatalog, tmp_path: Path, song: Path, output: bytes | None
) -> TrackFiles:
    copy = copied(library, tmp_path)
    (copy / song.relative_to(library.library_dir)).write_bytes(MONO_44_FRAME * 50)
    return TrackFiles(copy, LibraryRoot.at(library.library_dir), lambda _: output)


async def run_on(settings: Settings, library_dir: Path, query: str) -> httpx.Response:
    moved = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"library_dir": library_dir})}
    )
    application = create_app(moved)
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        client = await signed_in(application, "alice")
        response = await client.get(f"/api/run?{query}")
        await client.aclose()
    return response


async def direct_run(library: FixtureCatalog, tmp_path: Path, files: TrackFiles, ids: str) -> bytes:
    playlists = tmp_path / "_Playlists"
    playlists.mkdir()
    engine = catalog_engine(library.catalog_db)
    catalog = Catalog(
        SqlCatalog(CatalogDb(engine)),
        LibraryFiles(library.catalog_db, playlists, tmp_path / "covers"),
        PlaylistFiles(playlists),
        files,
        LibraryRoot.at(library.library_dir),
        NullCache(),
    )
    try:
        return b"".join([chunk async for chunk in await catalog.run(ids, 0.0)])
    finally:
        await engine.dispose()


async def test_a_run_streams_its_songs_back_to_back_on_their_lengths(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    (first, first_dur, first_path), (second, second_dur, _) = playable(library, 2)
    frames = FrameReader().push(first_path.read_bytes())

    response = await alice.get(f"/api/run?ids={first},{second}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert "content-length" not in response.headers
    assert response.content.startswith(b"".join(frames))
    assert len(frames_of(response.content)) == round((first_dur + second_dur) * PER_SECOND)


async def test_a_start_second_skips_into_the_first_song(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    [(first, first_dur, _)] = playable(library, 1)

    response = await alice.get(f"/api/run?ids={first}&at=1.5")

    assert response.status_code == 200
    assert len(frames_of(response.content)) == round((first_dur - 1.5) * PER_SECOND)


async def test_a_run_that_cannot_be_played_is_refused(
    alice: httpx.AsyncClient, client: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    [(first, first_dur, _)] = playable(library, 1)
    pending = fixture_rows(library, "SELECT id FROM tracks WHERE status='pending'")[0]
    expected = {
        f"ids={first}": (client, 401, "unauthorized"),
        "ids=": (alice, 400, "bad run"),
        f"ids={first},,{first}": (alice, 400, "bad run"),
        "ids=" + ",".join([str(first)] * 101): (alice, 400, "bad run"),
        f"ids={first}&at=-1": (alice, 400, "bad run"),
        f"ids={first}&at={first_dur}": (alice, 400, "bad run"),
        "ids=999999": (alice, 404, "no track"),
        f"ids={pending['id']}": (alice, 404, "no track"),
    }

    answers = {}
    for query, (who, _, _) in expected.items():
        response = await who.get(f"/api/run?{query}")
        answers[query] = (response.status_code, response.json()["detail"])

    assert answers == {query: (status, detail) for query, (_, status, detail) in expected.items()}


async def test_a_run_stops_before_a_song_it_cannot_play(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    (first, first_dur, _), (second, _, _) = playable(library, 2)
    untimed = fixture_rows(library, "SELECT id FROM tracks WHERE status='ok' AND dur IS NULL")[0]

    responses = [
        await alice.get(f"/api/run?ids={first},{blocked},{second}")
        for blocked in (999999, untimed["id"])
    ]

    assert [(item.status_code, len(frames_of(item.content))) for item in responses] == [
        (200, round(first_dur * PER_SECOND))
    ] * 2


async def test_a_run_whose_first_file_is_gone_is_404(
    settings: Settings, library: FixtureCatalog, tmp_path: Path
) -> None:
    [(first, _, _)] = playable(library, 1)
    empty = tmp_path / "empty-library"
    empty.mkdir()

    gone = await run_on(settings, empty, f"ids={first}")

    assert (gone.status_code, gone.json()) == (404, {"detail": "file gone"})


async def test_a_run_ends_at_a_song_whose_file_is_gone(
    settings: Settings, library: FixtureCatalog, tmp_path: Path
) -> None:
    copy = copied(library, tmp_path)
    (first, first_dur, _), (second, _, second_path) = playable(library, 2, within=copy)
    second_path.unlink()

    with capture_logs() as logs:
        response = await run_on(settings, copy, f"ids={first},{second}")

    assert response.status_code == 200
    assert len(frames_of(response.content)) == round(first_dur * PER_SECOND)
    cuts = [(entry["track"], entry["why"]) for entry in logs if entry["event"] == "run cut"]
    assert cuts == [(second, "file gone")]


async def test_a_song_in_another_format_is_re_encoded_into_the_run(
    library: FixtureCatalog, tmp_path: Path
) -> None:
    (first, first_dur, _), (second, second_dur, second_path) = playable(library, 2)
    files = other_format(library, tmp_path, second_path, ENCODED_FRAME * 30)

    frames = frames_of(await direct_run(library, tmp_path, files, f"{first},{second}"))

    slot = round(first_dur * PER_SECOND)
    assert len(frames) == round((first_dur + second_dur) * PER_SECOND)
    assert frames[slot : slot + 31] == [ENCODED_FRAME] * 30 + [silent_frame(STREAM_KIND)]


async def test_a_run_ends_at_a_song_that_cannot_be_re_encoded(
    library: FixtureCatalog, tmp_path: Path
) -> None:
    (first, first_dur, _), (second, _, second_path) = playable(library, 2)
    files = other_format(library, tmp_path, second_path, None)

    with capture_logs() as logs:
        frames = frames_of(await direct_run(library, tmp_path, files, f"{first},{second}"))

    assert len(frames) == round(first_dur * PER_SECOND)
    cuts = [(entry["track"], entry["why"]) for entry in logs if entry["event"] == "run cut"]
    assert cuts == [(second, "not playable")]


def test_files_hand_over_the_audio_file_and_a_re_encoding(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    (library / "Band").mkdir(parents=True)
    (library / "Band" / "native.mp3").write_bytes(mp3_bytes(5))
    (library / "Band" / "other.mp3").write_bytes(MONO_44_FRAME * 5)
    encoded: list[Path] = []

    def encoder(path: Path) -> bytes | None:
        encoded.append(path)
        return b"re-encoded"

    files = TrackFiles(library, LibraryRoot.at(library), encoder)
    native = files.open_audio("Band/native.mp3")

    assert native is not None
    with native:
        assert native.read() == mp3_bytes(5)
    assert files.reencoded("Band/other.mp3") == b"re-encoded"
    assert files.open_audio("Band/missing.mp3") is None
    assert files.reencoded("Band/missing.mp3") is None
    assert encoded == [library / "Band" / "other.mp3"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_ffmpeg_turns_another_format_into_the_stream_format(tmp_path: Path) -> None:
    source = tmp_path / "mono-44.mp3"
    source.write_bytes(MONO_44_FRAME * 200)

    output = reencode(source)

    assert output is not None
    reader = FrameReader()
    assert reader.push(output)
    assert reader.kind == STREAM_KIND
