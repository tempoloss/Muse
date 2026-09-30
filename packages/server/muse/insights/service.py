from datetime import timedelta
from typing import Any

from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.insights.domain import (
    BAD_WHO,
    DAY_MS,
    TOP_ARTISTS,
    WHO,
    PlayStats,
    common_artists,
    hours_histogram,
)
from muse.shared.clock import Clock
from muse.shared.errors import DomainError


class ListeningStats:
    def __init__(self, stats: PlayStats, catalog: Catalog, users: Users, clock: Clock) -> None:
        self.stats = stats
        self.catalog = catalog
        self.users = users
        self.clock = clock

    async def top_artists(
        self, user_id: str, since_ms: int, limit: int = TOP_ARTISTS
    ) -> list[dict[str, Any]]:
        return await self.stats.top_artists(user_id, since_ms, limit)

    async def summary(self, user_id: str, days: int, who: str) -> dict[str, Any]:
        if who not in WHO:
            raise DomainError(BAD_WHO)
        listener = user_id if who == "me" else self.users.partner_id(user_id)
        since = self.clock.now_ms() - days * DAY_MS
        plays, listened_ms = await self.stats.totals(listener, since)
        top = await self.stats.top_tracks(listener, since)
        starts = await self.stats.play_starts(listener, since)
        top_artists = await self.top_artists(listener, since)
        rows = await self.catalog.track_rows([track_id for track_id, _ in top])
        return {
            "plays": plays,
            "minutes": listened_ms // 60000,
            "top_artists": top_artists,
            "top_tracks": [
                {**rows[track_id], "plays": n} for track_id, n in top if track_id in rows
            ],
            "by_hour": hours_histogram(starts, self.clock.local_hour),
        }

    async def us(self, user_id: str, days: int) -> dict[str, Any]:
        partner_id = self.users.partner_id(user_id)
        since = self.clock.now_ms() - days * DAY_MS
        since_day = (self.clock.today() - timedelta(days=days - 1)).isoformat()
        seconds = await self.stats.together_seconds(since_day)
        both = await self.stats.both_likes(user_id, partner_id)
        ours = await self.stats.ours()
        letters = {
            "me": await self.stats.letters_sent(user_id, since),
            "partner": await self.stats.letters_sent(partner_id, since),
        }
        common = common_artists(
            await self.stats.artist_plays(user_id, since),
            await self.stats.artist_plays(partner_id, since),
        )
        songs = await self.stats.shared_songs(user_id, partner_id, since)
        rows = await self.catalog.track_rows([track_id for track_id, _, _ in songs])
        song = next(
            (
                {**rows[track_id], "me": a, "partner": b}
                for track_id, a, b in songs
                if track_id in rows
            ),
            None,
        )
        return {
            "together_minutes": int(seconds // 60),
            "both_likes": both,
            "ours": ours,
            "letters": letters,
            "common_artists": common,
            "song": song,
        }
