from collections.abc import Callable
from functools import partial
from pathlib import Path

import anyio
import structlog
from pywebpush import WebPushException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from muse.notifications.domain import PushMessage, Subscription
from muse.notifications.infra.sql import SqlSubscriptions
from muse.shared.db import UnitOfWork
from muse.shared.tasks import BackgroundRunner

PUSH_TTL_S = 86400
PUSH_TIMEOUT_S = 10
GONE = frozenset({404, 410})

type WebPush = Callable[..., object]

log = structlog.get_logger()


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []

    @property
    def public_key(self) -> str | None:
        return None

    async def send(self, user_id: str, message: PushMessage) -> None:
        self.sent.append((user_id, message.title, message.body, message.url))


class WebPushSender:
    def __init__(
        self,
        *,
        public_key: str,
        key_file: Path,
        subject: str,
        sessions: async_sessionmaker[AsyncSession],
        runner: BackgroundRunner,
        webpush: WebPush,
    ) -> None:
        self._public_key = public_key
        self.key_file = key_file
        self.subject = subject
        self.sessions = sessions
        self.runner = runner
        self.webpush = webpush

    @property
    def public_key(self) -> str | None:
        return self._public_key

    async def send(self, user_id: str, message: PushMessage) -> None:
        self.runner.spawn(self.deliver, user_id, message.payload(), name="push")

    async def deliver(self, user_id: str, payload: str) -> None:
        async with self.sessions() as session:
            subscriptions = await SqlSubscriptions(UnitOfWork(session)).of_user(user_id)
        for subscription in subscriptions:
            await self._push(user_id, subscription, payload)

    async def _push(self, user_id: str, subscription: Subscription, payload: str) -> None:
        post = partial(
            self.webpush,
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=str(self.key_file),
            vapid_claims={"sub": self.subject},
            ttl=PUSH_TTL_S,
            timeout=PUSH_TIMEOUT_S,
        )
        try:
            await anyio.to_thread.run_sync(post)
        except WebPushException as error:
            if getattr(error.response, "status_code", None) in GONE:
                await self._forget(subscription.endpoint)
            else:
                log.warning("push: delivery failed", user=user_id, error=str(error))
        except Exception as error:
            log.warning("push: delivery failed", user=user_id, error=str(error))

    async def _forget(self, endpoint: str) -> None:
        async with self.sessions() as session:
            uow = UnitOfWork(session)
            await SqlSubscriptions(uow).forget(endpoint)
            await uow.commit()
