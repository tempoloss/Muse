from muse.activity.domain import COUNTED, PLAYS_LIB
from muse.pet.domain import QuestPick
from muse.shared.db import UnitOfWork

PICKED = "SELECT kind, album_id, set_by FROM quest_day WHERE day=?"
PICK = "INSERT OR REPLACE INTO quest_day VALUES (?,?,?,?,?)"
ALBUM_HEARD = (
    f"SELECT p.user, COUNT(DISTINCT p.track_id) heard {PLAYS_LIB}WHERE p.started_at>=? "
    f"AND lib_t.album_id=? AND {COUNTED} GROUP BY p.user"
)
SHARED_LIKE = (
    "SELECT 1 FROM likes a JOIN likes b ON b.track_id=a.track_id AND b.user<>a.user "
    "WHERE MAX(a.created_at, b.created_at)>=? LIMIT 1"
)
LIKED_ONLY_BY = (
    "SELECT track_id FROM likes WHERE user=? AND track_id NOT IN "
    "(SELECT track_id FROM likes WHERE user=?) ORDER BY track_id"
)
LETTER_SENDERS = "SELECT COUNT(DISTINCT sender) FROM letters WHERE created_at>=?"
TOGETHER_SECONDS = "SELECT seconds FROM together WHERE day=?"


class SqlQuests:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def picked(self, day: str) -> QuestPick | None:
        row = await self.uow.row(PICKED, (day,))
        return QuestPick(row["kind"], row["album_id"], row["set_by"]) if row else None

    async def pick(self, day: str, chosen: QuestPick, at: int) -> None:
        await self.uow.execute(PICK, (day, chosen.kind, chosen.album_id, chosen.set_by, at))

    async def album_heard(self, since: int, album_id: int) -> dict[str, int]:
        rows = await self.uow.rows(ALBUM_HEARD, (since, album_id))
        return {row["user"]: row["heard"] for row in rows}

    async def shared_like_since(self, since: int) -> bool:
        return await self.uow.row(SHARED_LIKE, (since,)) is not None

    async def liked_only_by(self, liker: str, other: str) -> list[int]:
        rows = await self.uow.rows(LIKED_ONLY_BY, (liker, other))
        return [row["track_id"] for row in rows]

    async def letter_senders_since(self, since: int) -> int:
        return await self.uow.value(LETTER_SENDERS, (since,))

    async def together_seconds(self, day: str) -> float:
        seconds = await self.uow.value(TOGETHER_SECONDS, (day,))
        return seconds or 0
