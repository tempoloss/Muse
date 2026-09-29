import math
from datetime import date
from typing import Any

import httpx

from muse.settings import Settings
from tests.server.pet.support import (
    LETTERS_DAY,
    SAME_ALBUM_DAY,
    SHARED_LIKE_DAY,
    TOGETHER_DAY,
    PetTable,
    catalog_ids,
    noon_ms,
)
from tests.server.support import WRITE, ManualClock

VIEW = {
    "name",
    "born_at",
    "food",
    "joy",
    "energy",
    "clean",
    "sick",
    "asleep",
    "mood",
    "together_now",
    "quest",
    "log",
}


def on(clock: ManualClock, pet_table: PetTable, day: date, **fields: Any) -> None:
    clock.ms = noon_ms(day)
    pet_table.reset(**fields)


async def test_the_view_carries_the_quest_of_the_clocks_day(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    on(clock, pet_table, LETTERS_DAY)

    view = (await alice.get("/api/pet")).json()

    assert set(view) == VIEW
    assert view["together_now"] is False
    assert view["quest"] == {
        "kind": "letters",
        "text": "Обменяемся записками",
        "progress": 0,
        "goal": 2,
        "done": False,
        "album": None,
        "track": None,
        "parts": None,
        "picked_by": None,
    }


async def test_a_done_quest_is_rewarded_once_on_the_first_look(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    on(clock, pet_table, LETTERS_DAY, quest_paid=False, food=50, joy=50, energy=50, clean=50)
    for sender, recipient in (("alice", "bob"), ("bob", "alice"), ("bob", "alice")):
        pet_table.execute(
            "INSERT INTO letters(sender, recipient, track_id, text, created_at) VALUES (?,?,1,'hi',?)",
            (sender, recipient, clock.ms),
        )

    first = (await bob.get("/api/pet")).json()
    again = (await alice.get("/api/pet")).json()

    assert (first["quest"]["progress"], first["quest"]["done"]) == (2, True)
    assert [first[stat] for stat in ("food", "joy", "energy", "clean")] == [70] * 4
    assert again["food"] == 70
    assert pet_table.log("quest") == [(None, LETTERS_DAY.isoformat())]


async def test_the_shared_like_quest_offers_a_heart_the_viewer_has_not_given(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    pet_table: PetTable,
    clock: ManualClock,
    settings: Settings,
) -> None:
    on(clock, pet_table, SHARED_LIKE_DAY, quest_paid=False)
    first, second = catalog_ids(settings, "SELECT id FROM tracks WHERE status='ok' LIMIT 2")
    for track in (first, second):
        await bob.put(f"/api/likes/{track}", headers=WRITE)

    offered = (await alice.get("/api/pet")).json()["quest"]
    await alice.put(f"/api/likes/{first}", headers=WRITE)
    done = (await alice.get("/api/pet")).json()["quest"]

    assert (offered["kind"], offered["progress"], offered["goal"]) == ("shared_like", 0, 1)
    assert offered["track"]["id"] in {first, second}
    assert set(offered["track"]) == {"id", "num", "title", "dur", "album_id", "album", "artist"}
    assert (done["progress"], done["done"], done["track"]["id"]) == (1, True, second)


async def test_the_together_quest_counts_minutes_listened_together_today(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    on(clock, pet_table, TOGETHER_DAY)
    pet_table.execute(
        "INSERT INTO together(day, seconds) VALUES (?, 330.5), ('2026-01-20', 900)",
        (TOGETHER_DAY.isoformat(),),
    )

    quest = (await alice.get("/api/pet")).json()["quest"]

    assert (quest["kind"], quest["progress"], quest["goal"], quest["done"]) == (
        "together",
        5,
        10,
        False,
    )


async def test_the_drawn_album_quest_needs_most_of_the_album_from_both(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock
) -> None:
    on(clock, pet_table, SAME_ALBUM_DAY)

    quest = (await alice.get("/api/pet")).json()["quest"]
    album = quest["album"]

    assert quest["kind"] == "same_album"
    assert 5 <= album["ntracks"] <= 14
    assert album["need"] == max(1, math.ceil(album["ntracks"] * 0.8))
    assert quest["text"] == f"Послушаем альбом «{album['name']}» — {album['artist']}"
    assert quest["parts"] == [
        {"user": "alice", "progress": 0, "goal": album["need"]},
        {"user": "bob", "progress": 0, "goal": album["need"]},
    ]
    assert (quest["goal"], quest["picked_by"]) == (2 * album["need"], None)
