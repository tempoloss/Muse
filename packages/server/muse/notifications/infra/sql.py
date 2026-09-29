from muse.notifications.domain import Subscription
from muse.shared.db import UnitOfWork


class SqlSubscriptions:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def save(self, user_id: str, subscription: Subscription, at: int) -> None:
        await self.uow.execute(
            "INSERT OR REPLACE INTO push_subs VALUES (?,?,?,?,?)",
            (subscription.endpoint, user_id, subscription.p256dh, subscription.auth, at),
        )

    async def remove(self, user_id: str, endpoint: str) -> None:
        await self.uow.execute(
            "DELETE FROM push_subs WHERE endpoint=? AND user=?", (endpoint, user_id)
        )

    async def of_user(self, user_id: str) -> list[Subscription]:
        rows = await self.uow.rows(
            "SELECT endpoint, p256dh, auth FROM push_subs WHERE user=?", (user_id,)
        )
        return [Subscription(row["endpoint"], row["p256dh"], row["auth"]) for row in rows]

    async def forget(self, endpoint: str) -> None:
        await self.uow.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))
