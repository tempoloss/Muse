import pytest

from muse.shared.mp3 import (
    STREAM_KIND,
    SYNC_LIMIT,
    FrameReader,
    Joiner,
    Kind,
    frame_at,
    silent_frame,
)

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
    whole, pieces = FrameReader(), FrameReader()

    at_once = whole.push(data)
    piecewise = [piece for at in range(0, len(data), 7) for piece in pieces.push(data[at : at + 7])]

    assert piecewise == at_once
    assert [piece[4] for piece in at_once] == [1, 2, 3]
    assert (whole.kind, whole.done, pieces.kind, pieces.done) == (kind, True, kind, True)


def test_a_frame_of_another_kind_ends_the_audio() -> None:
    reader = FrameReader()

    frames = reader.push(song(STEREO_48, STEREO_48_SIZE, 2) + song(MONO_44, MONO_44_SIZE, 3))

    assert [piece[4] for piece in frames] == [1, 2]
    assert reader.done


def test_a_file_without_audio_near_its_start_is_given_up_on() -> None:
    reader = FrameReader()

    assert reader.push(bytes(SYNC_LIMIT)) == []
    assert not reader.done
    assert reader.push(bytes(1)) == []
    assert (reader.kind, reader.done) == (None, True)


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
    short = split(song(STEREO_48, STEREO_48_SIZE, 30, first_mark=1))
    long = split(song(STEREO_48, STEREO_48_SIZE, 60, first_mark=100))
    first_slot = round(1.0 * PER_SECOND)
    second_slot = round(2.0 * PER_SECOND) - first_slot

    joiner.song(1.0)
    first = joiner.take(short) + joiner.finish()
    joiner.song(1.0)
    second = joiner.take(long[:second_slot])
    left = joiner.left
    surplus = joiner.take(long[second_slot:]) + joiner.finish()

    frames = split(first + second)
    assert (left, surplus) == (0, b"")
    assert [piece[4] for piece in frames[:30]] == list(range(1, 31))
    assert frames[30:first_slot] == [silent_frame(STREAM_KIND)] * (first_slot - 30)
    assert [piece[4] for piece in frames[first_slot:]] == list(range(100, 100 + second_slot))


def test_a_start_second_skips_into_the_first_song() -> None:
    joiner = Joiner(STREAM_KIND)
    frames = split(song(STEREO_48, STEREO_48_SIZE, 60))

    joiner.song(1.2, start=0.24)
    body = joiner.take(frames[:5]) + joiner.take(frames[5:])

    skipped = round(0.24 * PER_SECOND)
    assert [piece[4] for piece in split(body)] == list(
        range(1 + skipped, 1 + skipped + round((1.2 - 0.24) * PER_SECOND))
    )
