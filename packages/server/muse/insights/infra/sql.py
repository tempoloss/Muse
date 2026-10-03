from typing import cast

from muse.activity.domain import COUNTED, PLAY_ARTIST, PLAYS_LIB
from muse.insights.domain import ArtistPlays
from muse.shared.db import UnitOfWork

COUNTED_FOR = f"WHERE p.user=? AND p.started_at>=? AND {COUNTED} "
WITH_ARTISTS = f"{PLAYS_LIB}LEFT JOIN lib.artists ar ON ar.name=lib_t.artist "
TOTALS = f"SELECT COUNT(*) plays, COALESCE(SUM(p.listened_ms), 0) ms {PLAYS_LIB}{COUNTED_FOR}"
TOP_TRACKS = (
    f"SELECT p.track_id, COUNT(*) n {PLAYS_LIB}{COUNTED_FOR}GROUP BY p.track_id "
    "ORDER BY n DESC, MAX(p.started_at) DESC LIMIT 10"
)
PLAY_STARTS = f"SELECT p.started_at {PLAYS_LIB}{COUNTED_FOR}"
ARTIST_PLAYS = f"SELECT {PLAY_ARTIST} name, COUNT(*) plays {WITH_ARTISTS}{COUNTED_FOR}"
TOP_ARTISTS = f"{ARTIST_PLAYS}GROUP BY {PLAY_ARTIST} ORDER BY plays DESC, name LIMIT ?"
PLAYS_BY_ARTIST = f"{ARTIST_PLAYS}GROUP BY {PLAY_ARTIST}"
SHARED_SONGS = (
    f"SELECT p.track_id, SUM(p.user=?) a, SUM(p.user=?) b {PLAYS_LIB}"
    f"WHERE p.started_at>=? AND {COUNTED} GROUP BY p.track_id HAVING a>=1 AND b>=1 "
    "ORDER BY MIN(a, b) DESC, a + b DESC LIMIT 5"
)


class SqlStats:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def totals(self, user_id: str, since_ms: int) -> tuple[int, int]:
        (row,) = await self.uow.rows(TOTALS, (user_id, since_ms))
        return row["plays"], row["ms"]

    async def top_tracks(self, user_id: str, since_ms: int) -> list[tuple[int, int]]:
        rows = await self.uow.rows(TOP_TRACKS, (user_id, since_ms))
        return [(row["track_id"], row["n"]) for row in rows]

    async def play_starts(self, user_id: str, since_ms: int) -> list[int]:
        rows = await self.uow.rows(PLAY_STARTS, (user_id, since_ms))
        return [row["started_at"] for row in rows]

    async def top_artists(self, user_id: str, since_ms: int, limit: int) -> list[ArtistPlays]:
        rows = await self.uow.rows(TOP_ARTISTS, (user_id, since_ms, limit))
        return cast("list[ArtistPlays]", rows)

    async def artist_plays(self, user_id: str, since_ms: int) -> dict[str, int]:
        rows = await self.uow.rows(PLAYS_BY_ARTIST, (user_id, since_ms))
        return {row["name"]: row["plays"] for row in rows}

    async def shared_songs(
        self, user_id: str, partner_id: str, since_ms: int
    ) -> list[tuple[int, int, int]]:
        rows = await self.uow.rows(SHARED_SONGS, (user_id, partner_id, since_ms))
        return [(row["track_id"], row["a"], row["b"]) for row in rows]

    async def together_seconds(self, since_day: str) -> float:
        return await self.uow.value(
            "SELECT COALESCE(SUM(seconds), 0) FROM together WHERE day>=?", (since_day,)
        )

    async def both_likes(self, user_id: str, partner_id: str) -> int:
        return await self.uow.value(
            "SELECT COUNT(*) FROM likes a JOIN likes b ON b.track_id=a.track_id AND b.user=? "
            "WHERE a.user=?",
            (partner_id, user_id),
        )

    async def ours(self) -> int:
        return await self.uow.value("SELECT COUNT(*) FROM ours")

    async def letters_sent(self, user_id: str, since_ms: int) -> int:
        return await self.uow.value(
            "SELECT COUNT(*) FROM letters WHERE sender=? AND created_at>=?", (user_id, since_ms)
        )
