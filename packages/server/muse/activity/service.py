from muse.activity.domain import (
    BAD_SOURCE,
    LISTENED_OUT_OF_RANGE,
    SOURCE_RE,
    LikeChanged,
    LikeRepository,
    Play,
    PlayRecorded,
    PlayRepository,
    listened_in_range,
    reached_now,
)
from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError
from muse.shared.events import EventBus


class Plays:
    def __init__(
        self,
        catalog: Catalog,
        plays: PlayRepository,
        bus: EventBus,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.catalog = catalog
        self.plays = plays
        self.bus = bus
        self.clock = clock
        self.uow = uow

    async def record(self, user_id: str, play: Play) -> None:
        duration = await self.catalog.playable_duration(play.track_id)
        if not listened_in_range(play.listened_ms, duration):
            raise DomainError(LISTENED_OUT_OF_RANGE)
        if not SOURCE_RE.fullmatch(play.source):
            raise DomainError(BAD_SOURCE)
        now = self.clock.now_ms()
        await self.plays.lock()
        previous = await self.plays.listened(user_id, play.track_id, play.started_at)
        await self.plays.save(user_id, play)
        reached = reached_now(play.listened_ms, previous, duration)
        await self.bus.publish(PlayRecorded(user_id, play.track_id, now, reached))
        await self.uow.commit()


class Likes:
    def __init__(
        self,
        catalog: Catalog,
        likes: LikeRepository,
        users: Users,
        bus: EventBus,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.catalog = catalog
        self.likes = likes
        self.users = users
        self.bus = bus
        self.clock = clock
        self.uow = uow

    async def like(self, user_id: str, track_id: int) -> None:
        await self.catalog.playable_duration(track_id)
        added = await self.likes.add(user_id, track_id, self.clock.now_ms())
        mutual = added and await self.likes.has(self.users.partner_id(user_id), track_id)
        await self.bus.publish(LikeChanged(user_id, track_id, liked=True, mutual_new=mutual))
        await self.uow.commit()

    async def unlike(self, user_id: str, track_id: int) -> None:
        await self.likes.remove(user_id, track_id)
        await self.bus.publish(LikeChanged(user_id, track_id, liked=False, mutual_new=False))
        await self.uow.commit()

    async def listing(self, user_id: str) -> dict[str, list[int]]:
        return {
            "me": await self.likes.track_ids(user_id),
            "partner": await self.likes.track_ids(self.users.partner_id(user_id)),
        }
