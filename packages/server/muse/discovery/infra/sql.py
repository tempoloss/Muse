from muse.activity.domain import COUNTED, PLAYS_LIB
from muse.catalog.domain import PLAYABLE, TRACK_COLUMNS
from muse.discovery.domain import Track
from muse.shared.db import CatalogDb, UnitOfWork

PLAYED_SINCE = "SELECT track_id FROM plays WHERE user=? AND started_at>=?"
COUNTED_SINCE = (
    f"SELECT DISTINCT p.track_id {PLAYS_LIB}WHERE p.user=? AND p.started_at>=? AND {COUNTED}"
)
LIKED = "SELECT track_id FROM likes WHERE user=?"
GENRE_TRACKS = f"SELECT {TRACK_COLUMNS} {PLAYABLE}AND al.genre=? ORDER BY t.id"


class SqlListeningHistory:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def _ids(self, sql: str, params: tuple[object, ...]) -> set[int]:
        return {row["track_id"] for row in await self.uow.rows(sql, params)}

    async def played_since(self, user_id: str, since_ms: int) -> set[int]:
        return await self._ids(PLAYED_SINCE, (user_id, since_ms))

    async def counted_since(self, user_id: str, since_ms: int) -> set[int]:
        return await self._ids(COUNTED_SINCE, (user_id, since_ms))

    async def liked(self, user_id: str) -> set[int]:
        return await self._ids(LIKED, (user_id,))


class SqlGenreTracks:
    def __init__(self, db: CatalogDb) -> None:
        self.db = db

    async def by_id(self, genre: str) -> list[Track]:
        return await self.db.rows(GENRE_TRACKS, (genre,))
