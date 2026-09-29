from typing import Any

import anyio

from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError
from muse.shared.events import EventBus
from muse.together.domain import (
    FOLLOW_POLL_S,
    PARTNER_FOLLOWS,
    Beat,
    LetterBox,
    LiveBoard,
    TogetherAccrued,
    TogetherLedger,
    live_partner,
    mirror,
    mirrored_track_id,
    shared_seconds,
)


class Live:
    def __init__(
        self,
        board: LiveBoard,
        ledger: TogetherLedger,
        letters: LetterBox,
        catalog: Catalog,
        users: Users,
        clock: Clock,
        bus: EventBus,
        uow: UnitOfWork,
    ) -> None:
        self.board = board
        self.ledger = ledger
        self.letters = letters
        self.catalog = catalog
        self.users = users
        self.clock = clock
        self.bus = bus
        self.uow = uow

    async def beat(
        self, user_id: str, track_id: int | None, position: float, playing: bool
    ) -> dict[str, Any]:
        if track_id is not None:
            await self.catalog.playable_duration(track_id)
        now = self.clock.now_ms()
        current = Beat(track_id, max(0.0, position), playing, now)
        previous, partner = self.board.report(user_id, self.users.partner_id(user_id), current)
        shared = shared_seconds(previous, current, partner)
        if shared is not None:
            total = await self.ledger.accrue(self.clock.today().isoformat(), shared)
            await self.bus.publish(TogetherAccrued(total - shared, total))
            await self.uow.commit()
        return await self._view(user_id, now)

    async def view(self, user_id: str) -> dict[str, Any]:
        return await self._view(user_id, self.clock.now_ms())

    async def _view(self, user_id: str, now: int) -> dict[str, Any]:
        beat, following = self.board.partner_state(self.users.partner_id(user_id), now)
        track_id = beat.track_id if beat else None
        partner = None
        if beat is not None and track_id is not None:
            track = (await self.catalog.track_rows([track_id])).get(track_id)
            partner = live_partner(beat, track, now, following) if track else None
        return {
            "partner": partner,
            "together": self.board.together_now(now),
            "unread": await self.letters.unread(user_id),
        }


class Following:
    def __init__(self, board: LiveBoard, catalog: Catalog, users: Users, clock: Clock) -> None:
        self.board = board
        self.catalog = catalog
        self.users = users
        self.clock = clock

    async def follow(self, user_id: str, since: int, wait: float) -> dict[str, Any]:
        partner_id = self.users.partner_id(user_id)
        if not self.board.start_following(user_id, partner_id, self.clock.now_ms()):
            raise DomainError(PARTNER_FOLLOWS)
        deadline = anyio.current_time() + wait
        while True:
            beat = self.board.beat_of(partner_id)
            if (beat is not None and beat.at != since) or anyio.current_time() >= deadline:
                return {"partner": await self._mirrored(beat, self.clock.now_ms())}
            await anyio.sleep(FOLLOW_POLL_S)

    def unfollow(self, user_id: str) -> None:
        self.board.stop_following(user_id)

    async def _mirrored(self, beat: Beat | None, now: int) -> dict[str, Any] | None:
        track_id = mirrored_track_id(beat, now)
        if beat is None or track_id is None:
            return None
        track = (await self.catalog.track_rows([track_id])).get(track_id)
        return mirror(beat, track, now) if track else None
