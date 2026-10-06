import shutil
from pathlib import Path

import httpx
import pytest
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.catalog.domain import LibraryRoot
from muse.catalog.infra.files import TrackFiles, reencode
from muse.settings import Settings
from muse.shared.mp3 import STREAM_KIND, audio_of, frame_at
from tests.fixtures.audio import mp3_bytes
from tests.fixtures.catalog import FixtureCatalog
from tests.server.catalog.support import fixture_rows
from tests.server.support import ORIGIN, signed_in

PER_SECOND = STREAM_KIND.rate / STREAM_KIND.samples
MONO_44_FRAME = bytes.fromhex("fffb90c4") + bytes(413)


def storage(library: Path) -> TrackFiles:
    return TrackFiles(library, LibraryRoot.at(library))


def playable(library: FixtureCatalog, count: int) -> list[tuple[int, int, Path]]:
    found: list[tuple[int, int, Path]] = []
    sql = "SELECT id, dur, path FROM tracks WHERE status='ok' AND dur > 0 ORDER BY id"
    for row in fixture_rows(library, sql):
        path = storage(library.library_dir).locate(row["path"])
        if path is not None:
            found.append((row["id"], row["dur"], path))
        if len(found) == count:
            break
    return found


def frame_count(stream: bytes) -> int:
    count = at = 0
    while at < len(stream):
        found = frame_at(stream, at)
        assert found is not None, f"no frame at byte {at}"
        assert found[0] == STREAM_KIND
        at += found[1]
        count += 1
    return count


async def test_a_run_streams_its_songs_back_to_back_on_their_lengths(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    (first, first_dur, first_path), (second, second_dur, _) = playable(library, 2)
    data = first_path.read_bytes()
    audio = audio_of(data)
    assert audio is not None

    response = await alice.get(f"/api/run?ids={first},{second}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert "content-length" not in response.headers
    assert response.content.startswith(data[audio.frames[0] : audio.frames[-1]])
    assert frame_count(response.content) == round((first_dur + second_dur) * PER_SECOND)


async def test_a_start_second_skips_into_the_first_song(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    [(first, first_dur, _)] = playable(library, 1)

    response = await alice.get(f"/api/run?ids={first}&at=1.5")

    assert response.status_code == 200
    assert frame_count(response.content) == round((first_dur - 1.5) * PER_SECOND)


async def test_a_run_that_cannot_be_played_is_refused(
    alice: httpx.AsyncClient, client: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    [(first, first_dur, _)] = playable(library, 1)
    untimed = fixture_rows(library, "SELECT id FROM tracks WHERE status='ok' AND dur IS NULL")[0]
    pending = fixture_rows(library, "SELECT id FROM tracks WHERE status='pending'")[0]
    expected = {
        f"ids={first}": (client, 401, "unauthorized"),
        "ids=": (alice, 400, "bad run"),
        f"ids={first},,{first}": (alice, 400, "bad run"),
        "ids=" + ",".join([str(first)] * 101): (alice, 400, "bad run"),
        f"ids={first}&at=-1": (alice, 400, "bad run"),
        f"ids={first}&at={first_dur}": (alice, 400, "bad run"),
        "ids=999999": (alice, 404, "no track"),
        f"ids={first},{untimed['id']}": (alice, 404, "no track"),
        f"ids={pending['id']}": (alice, 404, "no track"),
    }

    answers = {}
    for query, (who, _, _) in expected.items():
        response = await who.get(f"/api/run?{query}")
        answers[query] = (response.status_code, response.json()["detail"])

    assert answers == {query: (status, detail) for query, (_, status, detail) in expected.items()}


async def test_a_run_whose_first_file_is_gone_is_404(
    settings: Settings, library: FixtureCatalog, tmp_path: Path
) -> None:
    [(first, _, _)] = playable(library, 1)
    empty = tmp_path / "empty-library"
    empty.mkdir()
    moved = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"library_dir": empty})}
    )

    application = create_app(moved)
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        client = await signed_in(application, "alice")
        gone = await client.get(f"/api/run?ids={first}")
        await client.aclose()

    assert (gone.status_code, gone.json()) == (404, {"detail": "file gone"})


def test_a_file_in_another_format_is_handed_over_re_encoded(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    (library / "Band").mkdir(parents=True)
    (library / "Band" / "native.mp3").write_bytes(mp3_bytes(5))
    (library / "Band" / "other.mp3").write_bytes(MONO_44_FRAME * 5)
    encoded: list[Path] = []

    def encoder(path: Path) -> bytes | None:
        encoded.append(path)
        return b"re-encoded"

    files = TrackFiles(library, LibraryRoot.at(library), encoder)

    assert files.stream_bytes("Band/native.mp3") == mp3_bytes(5)
    assert files.stream_bytes("Band/other.mp3") == b"re-encoded"
    assert files.stream_bytes("Band/missing.mp3") is None
    assert encoded == [library / "Band" / "other.mp3"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_ffmpeg_turns_another_format_into_the_stream_format(tmp_path: Path) -> None:
    source = tmp_path / "mono-44.mp3"
    source.write_bytes(MONO_44_FRAME * 200)

    output = reencode(source)

    assert output is not None
    audio = audio_of(output)
    assert audio is not None
    assert audio.kind == STREAM_KIND
