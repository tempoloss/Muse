import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from litestar.types import ASGIApp, Message, Receive, Scope, Send
from litestar.types.asgi_types import HTTPResponseBodyEvent, HTTPResponseStartEvent, HTTPScope

MUTATING = frozenset({"POST", "PUT", "DELETE", "PATCH"})
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; "
    "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"DENY"),
)
RENEW_STATE_KEY = "muse_renew_sid"
SESSION_COOKIE = "muse_sid"
SESSION_MAX_AGE = 180 * 86400
type Headers = list[tuple[bytes, bytes]]


def renewal_cookie(token: str) -> bytes:
    return (
        f"{SESSION_COOKIE}={token}; Max-Age={SESSION_MAX_AGE}; Path=/; Secure; HttpOnly; "
        "SameSite=lax"
    ).encode("latin-1")


def api_cache_control(path: str, status: int) -> bytes:
    if status in (200, 206) and (path.startswith("/api/cover/") or path == "/api/artist-image"):
        return b"private, max-age=604800"
    if status in (200, 206) and path.startswith("/api/stream/"):
        return b"private, max-age=86400"
    return b"no-store"


def replaced(headers: Iterable[tuple[bytes, bytes]], updates: Headers) -> Headers:
    names = {name for name, _ in updates}
    return [(name, value) for name, value in headers if name.lower() not in names] + updates


def decorated_headers(start: HTTPResponseStartEvent, path: str, state: dict[str, Any]) -> Headers:
    headers: Headers = list(start["headers"])
    updates: Headers = list(SECURITY_HEADERS)
    content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
    if content_type.startswith(b"text/html"):
        updates.append((b"content-security-policy", CSP.encode("latin-1")))
    if path.startswith("/api/"):
        updates.append((b"cache-control", api_cache_control(path, start["status"])))
    headers = replaced(headers, updates)
    token = state.get(RENEW_STATE_KEY)
    if isinstance(token, str):
        headers.append((b"set-cookie", renewal_cookie(token)))
    return headers


def redirect_target(scope: HTTPScope, host: str) -> bytes:
    raw_path = scope.get("raw_path") or quote(scope["path"]).encode("latin-1")
    query = scope.get("query_string", b"")
    path = raw_path.split(b"?")[0]
    return f"https://{host}".encode("latin-1") + path + (b"?" + query if query else b"")


class HttpPolicy:
    def __init__(self, app: ASGIApp, *, origins: Iterable[str], public_host: str) -> None:
        self.app = app
        self.origins = frozenset(origins)
        self.public_host = public_host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope["headers"]
        }
        if '"scheme":"http"' in request_headers.get("cf-visitor", "").replace(" ", ""):
            host = request_headers.get("host") or self.public_host
            await self._respond(send, 308, [(b"location", redirect_target(scope, host))], b"")
            return
        path = scope["path"]
        state = scope["state"]

        async def policed_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = decorated_headers(message, path, state)
            await send(message)

        if (
            path.startswith("/api/")
            and scope["method"] in MUTATING
            and request_headers.get("origin") not in self.origins
        ):
            body = json.dumps({"detail": "bad origin"}).encode()
            await self._respond(policed_send, 403, [(b"content-type", b"application/json")], body)
            return
        await self.app(scope, receive, policed_send)

    @staticmethod
    async def _respond(send: Send, status: int, headers: Headers, body: bytes) -> None:
        start: HTTPResponseStartEvent = {
            "type": "http.response.start",
            "status": status,
            "headers": [*headers, (b"content-length", str(len(body)).encode())],
        }
        end: HTTPResponseBodyEvent = {
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        }
        await send(start)
        await send(end)
