from litestar import Litestar

from muse.notifications.domain import PushMessage
from muse.pet.service import HungerWatch
from tests.server.pet.support import HOUR_MS, PetTable
from tests.server.support import Inbox, ManualClock

HUNGRY = PushMessage(
    "🦊🐻 Лисёнок и Мишка проголодались",
    "Покорми их во вкладке «Мы» или просто включи музыку",
    "/us",
    "pet-hungry",
)


async def check_hunger(app: Litestar) -> None:
    async with app.state.dishka_container() as request:
        watch = await request.get(HungerWatch)
        await watch.check()


async def test_a_hungry_pet_calls_both_of_us_at_most_once_in_12_hours(
    app: Litestar, inbox: Inbox, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=24, joy=50, energy=50, clean=50)

    await check_hunger(app)
    await check_hunger(app)
    first = list(inbox.messages)
    clock.ms += 12 * HOUR_MS
    await check_hunger(app)
    quiet = list(inbox.messages)
    clock.ms += 1
    await check_hunger(app)

    assert first == quiet == [("alice", HUNGRY), ("bob", HUNGRY)]
    assert inbox.messages[2:] == [("alice", HUNGRY), ("bob", HUNGRY)]
    assert pet_table.log("hungry_push") == [(None, None), (None, None)]


async def test_a_fed_pet_only_has_its_decay_saved(
    app: Litestar, inbox: Inbox, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=29, joy=50, energy=50, clean=50, updated_at=clock.ms - HOUR_MS)

    await check_hunger(app)

    row = pet_table.row()
    assert (row["food"], row["updated_at"]) == (25, clock.ms)
    assert inbox.messages == []
    assert pet_table.log("hungry_push") == []
