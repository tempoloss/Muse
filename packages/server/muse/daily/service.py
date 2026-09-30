from datetime import date
from typing import Any

import structlog

from muse.catalog.service import Catalog
from muse.daily.domain import (
    DAILY_MIN_PLAYLISTS,
    NO_PLAYLIST,
    PAST_TITLES,
    TASTE_DAYS,
    Ask,
    DailyDraft,
    DailyStore,
    Listening,
    TasteSource,
    daily_build,
    daily_pool,
    daily_prompt,
    reply_playlists,
    shown_order,
)
from muse.discovery.domain import DAY_MS, RadioModel
from muse.discovery.service import RadioModels
from muse.identity.domain import Users
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError

log = structlog.get_logger()


class DailyPlaylists:
    def __init__(self, store: DailyStore, catalog: Catalog, clock: Clock) -> None:
        self.store = store
        self.catalog = catalog
        self.clock = clock

    async def latest(self, user_id: str) -> dict[str, Any]:
        day = await self.store.latest_day(self.clock.today().isoformat())
        rows = await self.store.of_day(day) if day else []
        playlists: list[dict[str, Any]] = []
        for row in shown_order(rows, user_id):
            tracks = await self.catalog.tracks_in_order(row["tracks"])
            if tracks:
                playlists.append(
                    {
                        "id": row["id"],
                        "for": row["for_user"],
                        "title": row["title"],
                        "blurb": row["blurb"],
                        "tracks": len(tracks),
                        "dur": sum(track["dur"] or 0 for track in tracks),
                        "albums": await self.catalog.cover_ids(tracks),
                    }
                )
        return {"day": day, "playlists": playlists}

    async def playlist(self, playlist_id: int) -> dict[str, Any] | None:
        row = await self.store.get(playlist_id)
        if row is None:
            return None
        tracks = await self.catalog.tracks_in_order(row["tracks"])
        return {
            "id": row["id"],
            "day": row["day"],
            "for": row["for_user"],
            "title": row["title"],
            "blurb": row["blurb"],
            "tracks": tracks,
            "albums": await self.catalog.cover_ids(tracks),
        }

    async def require(self, playlist_id: int) -> dict[str, Any]:
        found = await self.playlist(playlist_id)
        if found is None:
            raise DomainError(NO_PLAYLIST)
        return found


class DailyMaker:
    def __init__(
        self,
        models: RadioModels,
        store: DailyStore,
        taste: TasteSource,
        users: Users,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.models = models
        self.store = store
        self.taste = taste
        self.users = users
        self.clock = clock
        self.uow = uow

    async def exists(self, day: date) -> bool:
        return await self.store.exists(day.isoformat())

    async def make(self, day: date, ask: Ask) -> bool:
        model = await self.models.current()
        listening = await self._listening()
        pool = daily_pool(day, model, self.users.all, listening)
        past = await self.store.past_titles(day.isoformat(), PAST_TITLES)
        prompt = daily_prompt(day, pool, model, self.users.all, listening, past)
        pool_ids = {track["id"] for track in pool}
        async for name, reply in ask(prompt):
            drafts = self._usable(name, reply, pool_ids, model, day)
            if drafts is not None:
                await self._save(day, drafts, name)
                return True
        return False

    async def _listening(self) -> Listening:
        since = self.clock.now_ms() - TASTE_DAYS * DAY_MS
        user_ids = [user.id for user in self.users.all]
        likes = {user_id: await self.taste.likes(user_id) for user_id in user_ids}
        plays = {user_id: await self.taste.play_counts(user_id, since) for user_id in user_ids}
        return Listening(likes, plays, await self.taste.heard())

    def _usable(
        self, name: str, reply: str, pool_ids: set[int], model: RadioModel, day: date
    ) -> list[DailyDraft] | None:
        try:
            raw = reply_playlists(reply)
        except (ValueError, AttributeError) as error:
            log.warning(f"daily: {name}: no JSON ({error})")
            return None
        drafts = daily_build(raw, pool_ids, model, self.users.all, day)
        if len(drafts) < DAILY_MIN_PLAYLISTS:
            log.warning(f"daily: {name}: only {len(drafts)} usable playlists")
            return None
        return drafts

    async def _save(self, day: date, drafts: list[DailyDraft], name: str) -> None:
        await self.store.replace(day.isoformat(), drafts, name, self.clock.now_ms())
        await self.uow.commit()
        picks = ", ".join(f"{draft.picked}/{len(draft.tracks)}" for draft in drafts)
        log.info(f"daily: {day}: {len(drafts)} playlists by {name}, the model's own picks: {picks}")
