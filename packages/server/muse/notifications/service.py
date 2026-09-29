from muse.activity.domain import LikeChanged
from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.notifications.domain import (
    BAD_ENDPOINT,
    PushMessage,
    PushSender,
    Subscription,
    SubscriptionRepository,
    valid_endpoint,
)
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError


class Notifier:
    def __init__(self, sender: PushSender, uow: UnitOfWork) -> None:
        self.sender = sender
        self.uow = uow

    async def notify(self, user_id: str, title: str, body: str, url: str, tag: str) -> None:
        message = PushMessage(title, body, url, tag)

        async def deliver() -> None:
            await self.sender.send(user_id, message)

        self.uow.after_commit(deliver)


class PushSubscriptions:
    def __init__(
        self, subscriptions: SubscriptionRepository, clock: Clock, uow: UnitOfWork
    ) -> None:
        self.subscriptions = subscriptions
        self.clock = clock
        self.uow = uow

    async def subscribe(self, user_id: str, subscription: Subscription) -> None:
        if not valid_endpoint(subscription.endpoint):
            raise DomainError(BAD_ENDPOINT)
        await self.subscriptions.save(user_id, subscription, self.clock.now_ms())
        await self.uow.commit()

    async def unsubscribe(self, user_id: str, endpoint: str) -> None:
        await self.subscriptions.remove(user_id, endpoint)
        await self.uow.commit()


class PushReactions:
    def __init__(self, notifier: Notifier, catalog: Catalog, users: Users) -> None:
        self.notifier = notifier
        self.catalog = catalog
        self.users = users

    async def mutual_like(self, event: LikeChanged) -> None:
        if not event.mutual_new:
            return
        track = (await self.catalog.track_rows([event.track_id])).get(event.track_id)
        if track is None:
            return
        first, second = self.users.all
        await self.notifier.notify(
            self.users.partner_id(event.user),
            f"{first.emoji}{second.emoji} Совпало!",
            f"Теперь нам обоим нравится\n🎵 {track['title']} · {track['artist']}",
            "/us",
            f"like-{event.track_id}",
        )
