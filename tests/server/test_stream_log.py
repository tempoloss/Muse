from collections.abc import MutableMapping
from typing import Any, cast

import httpx
import pytest
from litestar.types import ASGIApp, Receive, Scope, Send
from structlog.testing import capture_logs

from muse.http.stream_log import StreamLog

type Message = dict[str, Any]
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"
FIELDS = ("track", "user", "device", "range", "if_range", "query", "status", "bytes", "end")


def streamed(logs: list[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [entry for entry in logs if entry["event"] == "stream request"]


async def run(app: ASGIApp) -> None:
    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(_: Message) -> None:
        return None

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream/7",
        "headers": [],
        "query_string": b"",
        "state": {},
    }
    await StreamLog(app)(cast("Scope", scope), cast("Receive", receive), cast("Send", send))


async def test_a_ranged_audio_request_is_logged_with_what_was_delivered(
    alice: httpx.AsyncClient, track_id: int
) -> None:
    asked = {"Range": "bytes=0-1", "If-Range": '"x"', "User-Agent": IPHONE}

    with capture_logs() as logs:
        response = await alice.get(f"/api/stream/{track_id}?retry=1", headers=asked)
        await alice.get("/api/me")

    [entry] = streamed(logs)
    assert response.status_code == 200
    assert {field: entry[field] for field in FIELDS} == {
        "track": str(track_id),
        "user": "alice",
        "device": "iPhone",
        "range": "bytes=0-1",
        "if_range": True,
        "query": "retry=1",
        "status": 200,
        "bytes": len(response.content),
        "end": "done",
    }


async def test_a_refused_audio_request_is_logged_without_a_user(
    client: httpx.AsyncClient, track_id: int
) -> None:
    with capture_logs() as logs:
        await client.get(f"/api/stream/{track_id}", headers={"Range": "bytes=0-1"})

    [entry] = streamed(logs)
    assert (entry["status"], entry["user"], entry["end"]) == (401, None, "done")


async def test_a_response_left_unfinished_is_cut_and_a_failure_is_aborted() -> None:
    async def left(_: Any, __: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 206, "headers": []})
        await send({"type": "http.response.body", "body": b"abc", "more_body": True})

    async def broken(_: Any, __: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise OSError("remote read failed")

    with capture_logs() as logs:
        await run(cast("ASGIApp", left))
        with pytest.raises(OSError, match="remote read failed"):
            await run(cast("ASGIApp", broken))

    assert [(entry["status"], entry["bytes"], entry["end"]) for entry in streamed(logs)] == [
        (206, 3, "cut"),
        (200, 0, "aborted"),
    ]
