from pathlib import Path

import anyio
import pytest
from litestar import Litestar, Request, Response, get
from litestar.response import Stream
from litestar.testing import AsyncTestClient

from muse.shared.ranges import RangeNotSatisfiableError, file_response, parse_range

SIZE = 10_000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("bytes=0-1023", (0, 1023)),
        ("bytes=500-", (500, 9999)),
        ("bytes=-500", (9500, 9999)),
        ("bytes=-20000", (0, 9999)),
        ("bytes=9000-20000", (9000, 9999)),
        ("BYTES = 1-2", (1, 2)),
        ("bytes=0-1,5-9", None),
        ("items=0-1", None),
        ("bytes=5-2", None),
        ("bytes=abc", None),
        ("bytes=-", None),
        ("bytes=0x10-", None),
    ],
)
def test_one_byte_range_is_honoured_and_anything_else_ignored(
    header: str | None, expected: tuple[int, int] | None
) -> None:
    assert parse_range(header, SIZE) == expected


@pytest.mark.parametrize("header", ["bytes=10000-", "bytes=-0", "bytes=20000-30000"])
def test_ranges_past_the_end_are_unsatisfiable(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, SIZE)


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "a.mp3"
    path.write_bytes(bytes(range(256)) * 400)
    return path


def make_app(path: Path) -> Litestar:
    @get("/file")
    async def serve(request: Request) -> Response[bytes] | Stream:
        return await file_response(path, "audio/mpeg", request)

    return Litestar([serve], openapi_config=None)


async def test_ranges_are_served_as_206_slices(audio: Path) -> None:
    body = await anyio.Path(audio).read_bytes()
    async with AsyncTestClient(make_app(audio)) as client:
        head = await client.get("/file", headers={"Range": "bytes=0-1023"})
        tail = await client.get("/file", headers={"Range": "bytes=-500"})
        whole = await client.get("/file")
        several = await client.get("/file", headers={"Range": "bytes=0-1,5-9"})
        beyond = await client.get("/file", headers={"Range": f"bytes={len(body)}-"})

    assert (head.status_code, head.content) == (206, body[:1024])
    assert head.headers["content-range"] == f"bytes 0-1023/{len(body)}"
    assert head.headers["content-length"] == "1024"
    assert head.headers["content-type"] == "audio/mpeg"
    assert (tail.status_code, tail.content) == (206, body[-500:])
    assert (whole.status_code, whole.content) == (200, body)
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.headers["content-length"] == str(len(body))
    assert whole.headers["etag"].startswith('"')
    assert "last-modified" in whole.headers
    assert (several.status_code, several.content) == (200, body)
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == f"bytes */{len(body)}"


async def test_if_range_must_name_the_current_file(audio: Path) -> None:
    async with AsyncTestClient(make_app(audio)) as client:
        current = (await client.get("/file")).headers
        stale = await client.get("/file", headers={"Range": "bytes=0-9", "If-Range": '"old"'})
        by_tag = await client.get(
            "/file", headers={"Range": "bytes=0-9", "If-Range": current["etag"]}
        )
        by_date = await client.get(
            "/file", headers={"Range": "bytes=0-9", "If-Range": current["last-modified"]}
        )

    assert stale.status_code == 200
    assert (by_tag.status_code, by_date.status_code) == (206, 206)
