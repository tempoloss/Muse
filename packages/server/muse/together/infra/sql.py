from muse.shared.db import UnitOfWork


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

    async def unread(self, user_id: str) -> int:
        return await self.uow.value(
            "SELECT COUNT(*) FROM letters WHERE recipient=? AND read_at IS NULL", (user_id,)
        )
