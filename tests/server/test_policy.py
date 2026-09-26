from typing import Any, cast

import pytest
from litestar.types import ASGIApp, Receive, Scope, Send

from muse.http.policy import HttpPolicy

type Message = dict[str, Any]


def fake_app(status: int, headers: list[tuple[bytes, bytes]], state: dict[str, object]) -> ASGIApp:
    async def app(scope: dict[str, Any], _: Any, send: Any) -> None:
        scope["state"].update(state)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    return cast("ASGIApp", app)


async def respond(
    path: str,
    status: int,
    headers: list[tuple[bytes, bytes]] | None = None,
    state: dict[str, object] | None = None,
) -> dict[str, list[str]]:
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    policy = HttpPolicy(
        fake_app(status, headers or [], state or {}),
        origins=["https://testserver.local"],
        public_host="music.example.org",
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "state": {},
    }
    await policy(cast("Scope", scope), cast("Receive", receive), cast("Send", send))
    found: dict[str, list[str]] = {}
    for name, value in sent[0]["headers"]:
        found.setdefault(name.decode(), []).append(value.decode())
    return found


@pytest.mark.parametrize(
    ("path", "status", "expected"),
    [
        ("/api/cover/7", 200, "private, max-age=604800"),
        ("/api/artist-image", 200, "private, max-age=604800"),
        ("/api/stream/7", 206, "private, max-age=86400"),
        ("/api/stream/7", 200, "private, max-age=86400"),
        ("/api/stream/7", 404, "no-store"),
        ("/api/cover/7", 404, "no-store"),
        ("/api/me", 200, "no-store"),
    ],
)
async def test_api_responses_get_their_cache_policy(path: str, status: int, expected: str) -> None:
    headers = await respond(path, status, [(b"cache-control", b"max-age=60")])

    assert headers["cache-control"] == [expected]


async def test_pages_keep_their_own_cache_policy_and_only_html_gets_a_csp() -> None:
    page = await respond("/x", 200, [(b"content-type", b"text/html; charset=utf-8")])
    data = await respond("/api/me", 200, [(b"content-type", b"application/json")])

    assert "cache-control" not in page
    assert "content-security-policy" in page
    assert "content-security-policy" not in data
    assert data["x-frame-options"] == ["DENY"]


async def test_a_renewed_session_re_sends_the_cookie() -> None:
    headers = await respond("/api/me", 200, state={"muse_renew_sid": "tok"})

    assert headers["set-cookie"] == [
        "muse_sid=tok; Max-Age=15552000; Path=/; Secure; HttpOnly; SameSite=lax"
    ]
