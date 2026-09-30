from muse.activity.domain import COUNTED, PLAYS_LIB
from muse.shared.db import UnitOfWork

SOURCES = (
    "SELECT source FROM plays WHERE user=? AND (source LIKE 'album:%' OR source LIKE 'playlist:%' "
    "OR source LIKE 'mix:%' OR source LIKE 'genre:%' OR source LIKE 'daily:%' OR source='ours') "
    "GROUP BY source ORDER BY MAX(started_at) DESC LIMIT 40"
)
RECENT = (
    "SELECT track_id FROM plays WHERE user=? GROUP BY track_id "
    "ORDER BY MAX(started_at) DESC LIMIT ?"
)
BOTH_LIKED = (
    "SELECT a.track_id FROM likes a JOIN likes b ON b.track_id=a.track_id AND b.user=? "
    "WHERE a.user=? ORDER BY MAX(a.created_at, b.created_at) DESC LIMIT 20"
)
GENRE_RANKING = (
    f"SELECT al.genre {PLAYS_LIB}JOIN lib.albums al ON al.id=lib_t.album_id "
    f"WHERE p.user=? AND p.started_at>=? AND {COUNTED} GROUP BY al.genre ORDER BY COUNT(*) DESC"
)
HEARD_ALBUMS = f"SELECT DISTINCT lib_t.album_id {PLAYS_LIB}WHERE p.user=? AND p.started_at>=?"


class SqlHome:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def recent_sources(self, user_id: str) -> list[str]:
        return [row["source"] for row in await self.uow.rows(SOURCES, (user_id,))]

    async def recent_track_ids(self, user_id: str, limit: int) -> list[int]:
        return [row["track_id"] for row in await self.uow.rows(RECENT, (user_id, limit))]

    async def both_liked(self, user_id: str, partner_id: str) -> list[int]:
        rows = await self.uow.rows(BOTH_LIKED, (partner_id, user_id))
        return [row["track_id"] for row in rows]

    async def genre_ranking(self, user_id: str, since_ms: int) -> list[str]:
        return [row["genre"] for row in await self.uow.rows(GENRE_RANKING, (user_id, since_ms))]

    async def heard_albums(self, user_id: str, since_ms: int) -> set[int]:
        rows = await self.uow.rows(HEARD_ALBUMS, (user_id, since_ms))
        return {row["album_id"] for row in rows}
