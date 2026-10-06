import pytest

from muse.shared.mp3 import STREAM_KIND, Joiner, Kind, audio_of, frame_at, silent_frame

STEREO_48 = bytes.fromhex("fffb9404")
STEREO_48_SIZE = 384
MONO_44 = bytes.fromhex("fffb90c4")
MONO_44_SIZE = 417
PER_SECOND = STREAM_KIND.rate / STREAM_KIND.samples


def frame(header: bytes, size: int, mark: int) -> bytes:
    return header + bytes([mark]) * (size - len(header))


def song(header: bytes, size: int, count: int, first_mark: int = 1) -> bytes:
    return b"".join(frame(header, size, first_mark + number) for number in range(count))


def id3(payload: bytes) -> bytes:
    size = len(payload)
    synchsafe = bytes(((size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F))
    return b"ID3\x03\x00\x00" + synchsafe + payload


def info(header: bytes, size: int, side: int) -> bytes:
    body = bytearray(frame(header, size, 0))
    body[4 + side : 8 + side] = b"Xing"
    return bytes(body)


def split(stream: bytes) -> list[bytes]:
    frames, at = [], 0
    while at < len(stream):
        found = frame_at(stream, at)
        assert found is not None, f"no frame at byte {at}"
        frames.append(stream[at : at + found[1]])
        at += found[1]
    return frames


@pytest.mark.parametrize(
    ("header", "size", "side", "kind"),
    [
        (STEREO_48, STEREO_48_SIZE, 32, Kind(3, 48000, mono=False)),
        (MONO_44, MONO_44_SIZE, 17, Kind(3, 44100, mono=True)),
    ],
)
def test_audio_starts_after_the_tags_and_the_info_frame_and_ends_before_trailing_tags(
    header: bytes, size: int, side: int, kind: Kind
) -> None:
    picture = b"cover art that happens to hold " + header + bytes(200)
    tail = b"TAG" + bytes(125)
    data = id3(picture) + info(header, size, side) + song(header, size, 3) + tail

    audio = audio_of(data)

    assert audio is not None
    assert audio.kind == kind
    assert [data[at + 4] for at in audio.frames[:-1]] == [1, 2, 3]
    assert audio.frames[-1] == len(data) - len(tail)


@pytest.mark.parametrize(
    "kind",
    [
        Kind(3, 48000, mono=False),
        Kind(3, 44100, mono=True),
        Kind(3, 32000, mono=False),
        Kind(2, 24000, mono=False),
        Kind(0, 8000, mono=True),
    ],
)
def test_silence_parses_back_as_a_frame_of_its_own_kind(kind: Kind) -> None:
    quiet = silent_frame(kind)

    assert frame_at(quiet, 0) == (kind, len(quiet))


def test_songs_are_laid_on_a_grid_of_their_catalog_lengths() -> None:
    joiner = Joiner(STREAM_KIND)
    short = song(STEREO_48, STEREO_48_SIZE, 30, first_mark=1)
    long = song(STEREO_48, STEREO_48_SIZE, 60, first_mark=100)

    first = joiner.add(short, 1.0)
    second = joiner.add(long, 1.0)

    assert first is not None
    assert second is not None
    frames = split(first + second)
    first_slot = round(1.0 * PER_SECOND)
    assert len(frames) == round(2.0 * PER_SECOND)
    assert [piece[4] for piece in frames[:30]] == list(range(1, 31))
    assert frames[30:first_slot] == [silent_frame(STREAM_KIND)] * (first_slot - 30)
    assert [piece[4] for piece in frames[first_slot:]] == list(
        range(100, 100 + len(frames) - first_slot)
    )


def test_a_start_second_skips_into_the_first_song() -> None:
    joiner = Joiner(STREAM_KIND)

    body = joiner.add(song(STEREO_48, STEREO_48_SIZE, 60), 1.2, start=0.24)

    assert body is not None
    skipped = round(0.24 * PER_SECOND)
    assert [piece[4] for piece in split(body)] == list(
        range(1 + skipped, 1 + skipped + round((1.2 - 0.24) * PER_SECOND))
    )


def test_a_song_of_another_kind_or_without_audio_is_refused_and_leaves_the_grid_alone() -> None:
    joiner = Joiner(STREAM_KIND)

    refused = [joiner.add(song(MONO_44, MONO_44_SIZE, 10), 1.0), joiner.add(b"not audio", 1.0)]
    body = joiner.add(song(STEREO_48, STEREO_48_SIZE, 50), 1.0)

    assert refused == [None, None]
    assert body is not None
    assert len(split(body)) == round(1.0 * PER_SECOND)
