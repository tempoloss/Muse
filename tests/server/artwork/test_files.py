import io
import os
from pathlib import Path

import pytest
from PIL import Image
from structlog.testing import capture_logs

from muse.artwork.infra.files import LocalArtworkFiles
from tests.fixtures.audio import mp3_bytes, with_cover


def image_bytes(size: tuple[int, int], color: tuple[int, ...], mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, "PNG" if mode == "RGBA" else "JPEG")
    return buffer.getvalue()


def average_color(path: Path) -> bytes:
    with Image.open(path) as image:
        return image.convert("RGB").resize((1, 1)).tobytes()


def touch_ns(path: Path, ns: int) -> None:
    os.utime(path, ns=(ns, ns))


@pytest.fixture
def files(tmp_path: Path) -> LocalArtworkFiles:
    return LocalArtworkFiles(tmp_path / "covers", tmp_path / "artists", tmp_path / "thumbs")


async def test_a_kept_image_replaces_the_previous_one_without_leftovers(
    files: LocalArtworkFiles, tmp_path: Path
) -> None:
    first = await files.covers.keep("12", b"one")
    second = await files.covers.keep("12", b"two")

    assert first == second == tmp_path / "covers" / "12.jpg"
    assert [path.name for path in (tmp_path / "covers").iterdir()] == ["12.jpg"]
    assert (await files.covers.image("12"), second.read_bytes()) == (second, b"two")
    assert await files.covers.image("13") is None


@pytest.mark.parametrize("size", [128, 384])
async def test_list_sizes_get_a_progressive_jpeg_that_fits_the_square(
    files: LocalArtworkFiles, tmp_path: Path, size: int
) -> None:
    source = await files.artists.keep("ab", image_bytes((768, 384), (10, 20, 30, 128), "RGBA"))

    thumb = await files.artists.thumbnail(source, size)

    assert thumb == tmp_path / "thumbs" / "artists" / str(size) / "ab.jpg"
    with Image.open(thumb) as image:
        assert (image.format, image.mode, image.size) == ("JPEG", "RGB", (size, size // 2))
        assert image.info.get("progressive") == 1


@pytest.mark.parametrize("size", [0, 64, 200, 600])
async def test_other_sizes_get_the_original(files: LocalArtworkFiles, size: int) -> None:
    source = await files.covers.keep("12", image_bytes((600, 600), (200, 0, 0)))

    assert await files.covers.thumbnail(source, size) == source


async def test_a_thumbnail_is_rebuilt_only_when_its_source_is_newer(
    files: LocalArtworkFiles,
) -> None:
    source = await files.covers.keep("12", image_bytes((600, 600), (200, 0, 0)))
    made = (await files.covers.thumbnail(source, 128)).stat().st_mtime_ns
    await files.covers.keep("12", image_bytes((600, 600), (0, 0, 200)))
    touch_ns(source, made - 1_000_000_000)
    kept = average_color(await files.covers.thumbnail(source, 128))
    touch_ns(source, made + 1_000_000_000)
    rebuilt = average_color(await files.covers.thumbnail(source, 128))

    assert (kept[0] > 150, rebuilt[2] > 150) == (True, True)


async def test_a_broken_image_is_served_at_full_size(
    files: LocalArtworkFiles, tmp_path: Path
) -> None:
    source = await files.covers.keep("12", b"not an image")

    with capture_logs() as logs:
        served = await files.covers.thumbnail(source, 128)

    assert served == source
    assert logs[0]["event"].startswith("thumbs: 12.jpg: ")
    assert not (tmp_path / "thumbs" / "covers" / "128" / "12.jpg").exists()


async def test_the_embedded_picture_of_a_track_is_read_when_there_is_one(
    files: LocalArtworkFiles, tmp_path: Path
) -> None:
    tagged, plain, junk = (tmp_path / name for name in ("a.mp3", "b.mp3", "c.mp3"))
    tagged.write_bytes(with_cover(mp3_bytes(8), b"picture"))
    plain.write_bytes(mp3_bytes(8))
    junk.write_bytes(b"junk")

    found = [await files.embedded_picture(path) for path in (tagged, plain, junk)]

    assert found == [b"picture", None, None]
    assert await files.embedded_picture(tmp_path / "missing.mp3") is None
