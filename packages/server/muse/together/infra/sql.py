from muse.shared.db import Row, UnitOfWork
from muse.together.domain import Letter, OursMark


def letter(row: Row) -> Letter:
    return Letter(
        id=row["id"],
        sender=row["sender"],
        recipient=row["recipient"],
        track_id=row["track_id"],
        text=row["text"],
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


class SqlTogether:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def accrue(self, day: str, seconds: float) -> float:
        await self.uow.execute(
            "INSERT INTO together(day, seconds) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET seconds=seconds+excluded.seconds",
            (day, seconds),
        )
        return await self.uow.value("SELECT seconds FROM together WHERE day=?", (day,))


class SqlLetters:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def send(self, sender: str, recipient: str, track_id: int, text: str, now: int) -> int:
        result = await self.uow.execute(
            "INSERT INTO letters(sender, recipient, track_id, text, created_at) VALUES (?,?,?,?,?)",
            (sender, recipient, track_id, text, now),
        )
        return result.lastrowid

    async def received(self, user_id: str) -> list[Letter]:
        rows = await self.uow.rows(
            "SELECT * FROM letters WHERE recipient=? ORDER BY created_at DESC, id DESC LIMIT 100",
            (user_id,),
        )
        return [letter(row) for row in rows]

    async def sent(self, user_id: str) -> list[Letter]:
        rows = await self.uow.rows(
            "SELECT * FROM letters WHERE sender=? ORDER BY created_at DESC, id DESC LIMIT 100",
            (user_id,),
        )
        return [letter(row) for row in rows]

    async def addressed_to(self, letter_id: int, user_id: str) -> bool:
        found = await self.uow.value(
            "SELECT 1 FROM letters WHERE id=? AND recipient=?", (letter_id, user_id)
        )
        return found is not None

    async def mark_read(self, letter_id: int, now: int) -> None:
        await self.uow.execute(
            "UPDATE letters SET read_at=? WHERE id=? AND read_at IS NULL", (now, letter_id)
        )

    async def unread(self, user_id: str) -> int:
        return await self.uow.value(
            "SELECT COUNT(*) FROM letters WHERE recipient=? AND read_at IS NULL", (user_id,)
        )


class SqlOurs:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def marks(self) -> list[OursMark]:
        rows = await self.uow.rows(
            "SELECT track_id, added_by, added_at FROM ours ORDER BY added_at DESC, rowid DESC"
        )
        return [OursMark(row["track_id"], row["added_by"], row["added_at"]) for row in rows]

    async def add(self, track_id: int, user_id: str, now: int) -> bool:
        result = await self.uow.execute(
            "INSERT OR IGNORE INTO ours VALUES (?,?,?)", (track_id, user_id, now)
        )
        return result.rowcount == 1

    async def remove(self, track_id: int) -> None:
        await self.uow.execute("DELETE FROM ours WHERE track_id=?", (track_id,))
