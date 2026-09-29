import httpx

from tests.server.pet.support import DAY_MS, HOUR_MS, PetTable
from tests.server.support import WRITE, ManualClock

STATS = ("food", "joy", "energy", "clean")


async def care(client: httpx.AsyncClient, action: str) -> httpx.Response:
    return await client.post(f"/api/pet/{action}", headers=WRITE)


async def test_a_neglected_pet_gets_sick_and_both_carers_nurse_it_back(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=50, joy=50, energy=50, clean=50, updated_at=clock.ms - 30 * HOUR_MS)

    view = (await alice.get("/api/pet")).json()
    assert (view["food"], view["sick"], view["mood"]) == (0, True, "sick")
    fed = (await care(alice, "feed")).json()
    assert (fed["food"], fed["halved"]) == (25, False)
    again = (await care(alice, "feed")).json()
    assert (again["food"], again["halved"]) == (38, True)
    assert (await care(bob, "feed")).json()["halved"] is False
    healed = (await care(bob, "heal")).json()
    assert healed["sick"] is False
    assert all(healed[stat] >= 30 for stat in STATS), healed
    healthy = await care(bob, "heal")
    assert (healthy.status_code, healthy.json()) == (409, {"detail": "healthy"})
    assert (await care(alice, "sleep")).json()["asleep"] is True
    asleep = await care(bob, "feed")
    assert (asleep.status_code, asleep.json()) == (409, {"detail": "asleep"})
    assert (await care(bob, "sleep")).json()["asleep"] is False
    dance = await care(alice, "dance")
    assert (dance.status_code, dance.json()) == (404, {"detail": "no such action"})
    assert len(pet_table.log("bonus")) == 1


async def test_a_refused_action_changes_nothing(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=50, joy=50, energy=5, clean=50, updated_at=clock.ms - HOUR_MS)

    tired = await care(alice, "play")

    assert (tired.status_code, tired.json()) == (409, {"detail": "tired"})
    assert (pet_table.row()["updated_at"], pet_table.log("play")) == (clock.ms - HOUR_MS, [])


async def test_turns_are_halved_for_six_hours_per_action(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=10, joy=10, energy=90, clean=10)

    assert (await care(alice, "wash")).json()["halved"] is False
    assert (await care(alice, "play")).json()["halved"] is False
    assert (await care(alice, "wash")).json()["halved"] is True
    clock.ms += 6 * HOUR_MS + 1
    assert (await care(alice, "wash")).json()["halved"] is False


async def test_the_two_carer_bonus_is_paid_once_a_day(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(food=10, joy=10, energy=50, clean=10)

    await care(alice, "wash")
    assert pet_table.log("bonus") == []
    bonus = (await care(bob, "wash")).json()
    await care(alice, "play")
    first_day = clock.today().isoformat()
    clock.ms += DAY_MS
    await care(alice, "feed")
    await care(bob, "feed")

    assert (bonus["food"], bonus["joy"], bonus["energy"], bonus["clean"]) == (20, 30, 60, 100)
    assert pet_table.log("bonus") == [(None, first_day), (None, clock.today().isoformat())]


async def test_the_pet_is_renamed_with_trimmed_names_of_1_to_24_characters(
    alice: httpx.AsyncClient, pet_table: PetTable
) -> None:
    pet_table.reset()

    renamed = await alice.put("/api/pet/name", json={"name": "  Пушок  "}, headers=WRITE)
    blank = await alice.put("/api/pet/name", json={"name": "   "}, headers=WRITE)
    long = await alice.put("/api/pet/name", json={"name": "x" * 25}, headers=WRITE)

    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["log"][0]) == (
        "Пушок",
        {"at": pet_table.clock.ms, "user": "alice", "action": "name"},
    )
    for refused in (blank, long):
        assert (refused.status_code, refused.json()) == (422, {"detail": "bad name"})
    assert pet_table.log("name") == [("alice", "Пушок")]


async def test_the_log_shows_the_eight_latest_entries_without_music_or_reminders(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    pet_table.reset(quest_paid=False)
    for minute, action in enumerate(["feed"] * 4 + ["music", "hungry_push"] + ["play"] * 6):
        pet_table.execute(
            "INSERT INTO pet_log(at, user, action, detail) VALUES (?, 'bob', ?, NULL)",
            (clock.ms - (20 - minute) * 60000, action),
        )

    log = (await alice.get("/api/pet")).json()["log"]

    assert [entry["action"] for entry in log] == ["play"] * 6 + ["feed"] * 2
    assert log[0] == {"at": clock.ms - 9 * 60000, "user": "bob", "action": "play"}
