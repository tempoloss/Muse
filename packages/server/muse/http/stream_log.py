import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from litestar.types import ASGIApp, Message, Receive, Scope, Send

from muse.diagnostics.domain import device
from muse.identity.domain import User

STREAM_PATH = "/api/stream/"
RUN_PATH = "/api/run"
MS = 1000

log = structlog.get_logger()


@dataclass(slots=True)
class Delivery:
    status: int | None = None
    first: float | None = None
    body: float | None = None
    sent: int = 0
    complete: bool = False


def header(scope: Scope, name: bytes) -> str | None:
    return next((value.decode("latin-1") for key, value in scope["headers"] if key == name), None)


def audio_track(path: str) -> str | None:
    if path.startswith(STREAM_PATH):
        return path.removeprefix(STREAM_PATH)
    return "run" if path == RUN_PATH else None


class StreamLog:
    def __init__(self, app: ASGIApp, clock: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        track = audio_track(scope["path"]) if scope["type"] == "http" else None
        if track is None:
            await self.app(scope, receive, send)
            return
        started = self.clock()
        delivery = Delivery()

        async def counted(message: Message) -> None:
            if message["type"] == "http.response.start":
                delivery.status = message["status"]
                delivery.first = self.clock() - started
            elif message["type"] == "http.response.body":
                delivery.sent += len(message["body"])
                if message["body"] and delivery.body is None:
                    delivery.body = self.clock() - started
                delivery.complete = not message.get("more_body", False)
            await send(message)

        returned = False
        try:
            await self.app(scope, receive, counted)
            returned = True
        finally:
            user = scope.get("user")
            log.info(
                "stream request",
                track=track,
                user=user.id if isinstance(user, User) else None,
                device=device(header(scope, b"user-agent") or ""),
                range=header(scope, b"range"),
                if_range=header(scope, b"if-range") is not None,
                query=scope["query_string"].decode("latin-1") or None,
                status=delivery.status,
                bytes=delivery.sent,
                first_ms=None if delivery.first is None else round(delivery.first * MS),
                body_ms=None if delivery.body is None else round(delivery.body * MS),
                ms=round((self.clock() - started) * MS),
                end="done" if delivery.complete else "cut" if returned else "aborted",
            )
