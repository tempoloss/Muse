import json
from collections.abc import Sequence

from muse.activity.domain import COUNTED, PLAYS_LIB
from muse.daily.domain import DailyDraft, Row
from muse.shared.db import UnitOfWork

EXISTS = "SELECT 1 FROM daily WHERE day=? LIMIT 1"
PAST_TITLES = "SELECT title FROM daily WHERE day<? ORDER BY day DESC, slot LIMIT ?"
DELETE_DAY = "DELETE FROM daily WHERE day=?"
INSERT = (
    "INSERT INTO daily(day, slot, for_user, title, blurb, tracks, model, created_at) "
    "VALUES (?,?,?,?,?,?,?,?)"
)
BY_ID = "SELECT * FROM daily WHERE id=?"
LATEST_DAY = "SELECT MAX(day) FROM daily WHERE day<=?"
OF_DAY = "SELECT * FROM daily WHERE day=? ORDER BY slot"
LIKES = "SELECT track_id FROM likes WHERE user=? ORDER BY created_at DESC"
PLAY_COUNTS = (
    f"SELECT p.track_id, COUNT(*) plays {PLAYS_LIB}WHERE p.user=? AND p.started_at>=? "
    f"AND {COUNTED} GROUP BY p.track_id"
)
HEARD = "SELECT DISTINCT track_id FROM plays"


def decoded(row: Row) -> Row:
    return {**row, "tracks": json.loads(row["tracks"])}


class SqlDailyStore:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def exists(self, day: str) -> bool:
        return await self.uow.row(EXISTS, (day,)) is not None

    async def past_titles(self, day: str, limit: int) -> list[str]:
        return [row["title"] for row in await self.uow.rows(PAST_TITLES, (day, limit))]

    async def replace(self, day: str, drafts: Sequence[DailyDraft], model: str, now: int) -> None:
        await self.uow.execute(DELETE_DAY, (day,))
        for slot, draft in enumerate(drafts):
            values = (draft.owner, draft.title, draft.blurb, json.dumps(draft.tracks))
            await self.uow.execute(INSERT, (day, slot, *values, model, now))

    async def get(self, playlist_id: int) -> Row | None:
        row = await self.uow.row(BY_ID, (playlist_id,))
        return decoded(row) if row is not None else None

    async def latest_day(self, today: str) -> str | None:
        return await self.uow.value(LATEST_DAY, (today,))

    async def of_day(self, day: str) -> list[Row]:
        return [decoded(row) for row in await self.uow.rows(OF_DAY, (day,))]


class SqlTasteSource:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def likes(self, user_id: str) -> list[int]:
        return [row["track_id"] for row in await self.uow.rows(LIKES, (user_id,))]

    async def play_counts(self, user_id: str, since_ms: int) -> dict[int, int]:
        rows = await self.uow.rows(PLAY_COUNTS, (user_id, since_ms))
        return {row["track_id"]: row["plays"] for row in rows}

    async def heard(self) -> set[int]:
        return {row["track_id"] for row in await self.uow.rows(HEARD)}
