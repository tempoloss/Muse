import base64
import copy
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from litestar.testing import AsyncTestClient
from py_vapid import Vapid01
from pywebpush import WebPushException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from muse.app import create_app
from muse.notifications.domain import PushMessage
from muse.notifications.infra.sender import WebPushSender
from muse.settings import PushSettings, Settings
from muse.shared.tasks import BackgroundRunner
from tests.server.support import ORIGIN, signed_in

SUBJECT = "mailto:push@example.org"


@dataclass(frozen=True)
class Answer:
    status_code: int


class PushService:
    def __init__(self, failures: dict[str, Exception]) -> None:
        self.failures = failures
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **request: Any) -> None:
        self.calls.append(copy.deepcopy(request))
        request["vapid_claims"]["aud"] = "https://push.example.org"
        failure = self.failures.get(request["subscription_info"]["endpoint"])
        if failure is not None:
            raise failure


def subscribe(settings: Settings, rows: list[tuple[str, str]]) -> None:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        db.executemany(
            "INSERT INTO push_subs VALUES (?, ?, 'p256', 'secret', 1)",
            [(endpoint, user) for endpoint, user in rows],
        )
        db.commit()


def endpoints(settings: Settings) -> list[str]:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        return [row[0] for row in db.execute("SELECT endpoint FROM push_subs ORDER BY endpoint")]


def enabled(settings: Settings) -> Settings:
    return settings.model_copy(update={"push": PushSettings(enabled=True, subject=SUBJECT)})


async def push_key(settings: Settings) -> str:
    app = create_app(settings)
    async with AsyncTestClient(app=app, base_url=ORIGIN):
        alice = await signed_in(app, "alice")
        key = (await alice.get("/api/push/key")).json()["key"]
        await alice.aclose()
    return key


async def test_the_application_server_key_is_made_once_and_kept(settings: Settings) -> None:
    push = enabled(settings)
    assert not push.paths.vapid_file.exists()

    first = await push_key(push)
    again = await push_key(push)

    raw = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))
    stored = Vapid01.from_file(str(push.paths.vapid_file)).public_key
    assert raw == stored.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    assert (len(raw), raw[0], "=" in first) == (65, 4, False)
    assert again == first


async def test_delivery_posts_every_subscription_and_forgets_the_ones_the_browser_dropped(
    settings: Settings, sessions: async_sessionmaker[AsyncSession]
) -> None:
    base = "https://push.example.org/"
    subscribe(
        settings,
        [(base + name, "alice") for name in ("a-ok", "b-gone", "c-missing", "d-busy", "e-down")]
        + [(base + "f-bob", "bob")],
    )
    service = PushService(
        {
            base + "b-gone": WebPushException("Push failed: 410", response=Answer(410)),
            base + "c-missing": WebPushException("Push failed: 404", response=Answer(404)),
            base + "d-busy": WebPushException("Push failed: 503", response=Answer(503)),
            base + "e-down": ConnectionError("unreachable"),
        }
    )
    sender = WebPushSender(
        public_key="key",
        key_file=settings.paths.vapid_file,
        subject=SUBJECT,
        sessions=sessions,
        runner=BackgroundRunner(),
        webpush=service,
    )
    payload = PushMessage("🦊🐻 Совпало!", "Теперь нам обоим нравится", "/us", "like-7").payload()

    with capture_logs() as logs:
        await sender.deliver("alice", payload)

    assert [call["subscription_info"]["endpoint"] for call in service.calls] == [
        base + name for name in ("a-ok", "b-gone", "c-missing", "d-busy", "e-down")
    ]
    assert service.calls[0] == {
        "subscription_info": {
            "endpoint": base + "a-ok",
            "keys": {"p256dh": "p256", "auth": "secret"},
        },
        "data": payload,
        "vapid_private_key": str(settings.paths.vapid_file),
        "vapid_claims": {"sub": SUBJECT},
        "ttl": 86400,
        "timeout": 10,
    }
    assert all(call["vapid_claims"] == {"sub": SUBJECT} for call in service.calls)
    assert endpoints(settings) == [base + "a-ok", base + "d-busy", base + "e-down", base + "f-bob"]
    assert [(entry["log_level"], entry["user"]) for entry in logs] == [
        ("warning", "alice"),
        ("warning", "alice"),
    ]


def test_the_payload_keeps_non_ascii_text_readable() -> None:
    payload = PushMessage("🦊🐻 Совпало!", "Песня · Артист", "/us", "like-7").payload()

    assert json.loads(payload) == {
        "title": "🦊🐻 Совпало!",
        "body": "Песня · Артист",
        "url": "/us",
        "tag": "like-7",
    }
    assert "Совпало" in payload
