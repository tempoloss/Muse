from muse.identity.domain import SESSION_TTL_S, LiveSession
from muse.shared.db import UnitOfWork


class SqlSessions:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def purge_expired(self, now: int) -> None:
        await self.uow.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))

    async def create(self, digest: str, user_id: str, now: int, user_agent: str) -> None:
        await self.uow.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
            (digest, user_id, now, now, now + SESSION_TTL_S, user_agent),
        )

    async def find_live(self, digest: str, now: int) -> LiveSession | None:
        row = await self.uow.row(
            "SELECT user, last_seen FROM sessions WHERE token_hash=? AND expires_at>?",
            (digest, now),
        )
        return LiveSession(row["user"], row["last_seen"]) if row else None

    async def renew(self, digest: str, now: int) -> None:
        await self.uow.execute(
            "UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
            (now, now + SESSION_TTL_S, digest),
        )

    async def delete(self, digest: str) -> None:
        await self.uow.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
