from collections.abc import Sequence
from typing import cast

from muse.pet.domain import CARE_LOG, LogEntry, Pet
from muse.shared.db import UnitOfWork

CARE_MARKS = ",".join("?" * len(CARE_LOG))
LOCK = "UPDATE pet SET id=id WHERE id=1"
LOAD = "SELECT * FROM pet WHERE id=1"
SAVE = (
    "UPDATE pet SET food=?, joy=?, energy=?, clean=?, sick=?, asleep_until=?, updated_at=? "
    "WHERE id=1"
)
RENAME = "UPDATE pet SET name=? WHERE id=1"
LOG = "INSERT INTO pet_log(at, user, action, detail) VALUES (?,?,?,?)"
LOGGED = "SELECT 1 FROM pet_log WHERE action=? AND detail=?"
MUSIC_FED = (
    "SELECT COALESCE(SUM(CAST(detail AS REAL)), 0) FROM pet_log WHERE action='music' AND at>=?"
)
LAST_CARER = "SELECT user FROM pet_log WHERE action=? AND at>=? ORDER BY at DESC, id DESC LIMIT 1"
CARERS = (
    f"SELECT COUNT(DISTINCT user) FROM pet_log WHERE at>=? AND action IN ({CARE_MARKS}) "
    "AND user IN (?, ?)"
)
RECENT = (
    "SELECT at, user, action FROM pet_log WHERE action NOT IN ('music', 'hungry_push') "
    "ORDER BY at DESC, id DESC LIMIT 8"
)
HUNGRY_PUSHED = "SELECT 1 FROM pet_log WHERE action='hungry_push' AND at>=?"


class PetRowMissingError(LookupError):
    pass


class SqlPets:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def lock(self) -> None:
        await self.uow.execute(LOCK)

    async def load(self) -> Pet:
        row = await self.uow.row(LOAD)
        if row is None:
            raise PetRowMissingError("pet row missing; run: muse db upgrade")
        return Pet(
            name=row["name"],
            born_at=row["born_at"],
            food=row["food"],
            joy=row["joy"],
            energy=row["energy"],
            clean=row["clean"],
            sick=bool(row["sick"]),
            asleep_until=row["asleep_until"],
            updated_at=row["updated_at"],
        )

    async def save(self, pet: Pet) -> None:
        await self.uow.execute(
            SAVE,
            (
                pet.food,
                pet.joy,
                pet.energy,
                pet.clean,
                int(pet.sick),
                pet.asleep_until,
                pet.updated_at,
            ),
        )

    async def rename(self, name: str) -> None:
        await self.uow.execute(RENAME, (name,))

    async def log(self, at: int, user: str | None, action: str, detail: str | None = None) -> None:
        await self.uow.execute(LOG, (at, user, action, detail))

    async def logged(self, action: str, detail: str) -> bool:
        return await self.uow.row(LOGGED, (action, detail)) is not None

    async def music_fed_since(self, since: int) -> float:
        return await self.uow.value(MUSIC_FED, (since,))

    async def last_carer(self, action: str, since: int) -> str | None:
        return await self.uow.value(LAST_CARER, (action, since))

    async def carers_since(self, since: int, user_ids: Sequence[str]) -> int:
        return await self.uow.value(CARERS, (since, *CARE_LOG, *user_ids))

    async def recent_log(self) -> list[LogEntry]:
        return cast("list[LogEntry]", await self.uow.rows(RECENT))

    async def hungry_pushed_since(self, since: int) -> bool:
        return await self.uow.row(HUNGRY_PUSHED, (since,)) is not None
