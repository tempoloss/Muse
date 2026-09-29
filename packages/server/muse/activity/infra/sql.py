from muse.activity.domain import Play
from muse.shared.db import UnitOfWork


class SqlPlays:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def lock(self) -> None:
        await self.uow.execute("UPDATE plays SET user=user WHERE 0")

    async def listened(self, user: str, track_id: int, started_at: int) -> int | None:
        return await self.uow.value(
            "SELECT listened_ms FROM plays WHERE user=? AND track_id=? AND started_at=?",
            (user, track_id, started_at),
        )

    async def save(self, user: str, play: Play) -> None:
        await self.uow.execute(
            "INSERT OR REPLACE INTO plays VALUES (?,?,?,?,?,?,?)",
            (
                user,
                play.track_id,
                play.started_at,
                play.listened_ms,
                int(play.completed),
                int(play.skipped),
                play.source,
            ),
        )


class SqlLikes:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def add(self, user: str, track_id: int, at: int) -> bool:
        result = await self.uow.execute(
            "INSERT OR IGNORE INTO likes VALUES (?,?,?)", (user, track_id, at)
        )
        return result.rowcount == 1

    async def has(self, user: str, track_id: int) -> bool:
        found = await self.uow.row(
            "SELECT 1 FROM likes WHERE user=? AND track_id=?", (user, track_id)
        )
        return found is not None

    async def remove(self, user: str, track_id: int) -> None:
        await self.uow.execute("DELETE FROM likes WHERE user=? AND track_id=?", (user, track_id))

    async def track_ids(self, user: str) -> list[int]:
        rows = await self.uow.rows(
            "SELECT track_id FROM likes WHERE user=? ORDER BY created_at DESC", (user,)
        )
        return [row["track_id"] for row in rows]
