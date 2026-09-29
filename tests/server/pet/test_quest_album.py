import httpx
import pytest

from muse.notifications.domain import PushMessage
from muse.settings import Settings
from tests.server.pet.support import (
    SHARED_LIKE_DAY,
    PetTable,
    catalog_ids,
    catalog_rows,
    noon_ms,
    play,
)
from tests.server.support import WRITE, Inbox, ManualClock


@pytest.fixture
def album_id(settings: Settings) -> int:
    return catalog_ids(
        settings, "SELECT album_id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 1"
    )[0]


async def test_the_album_quest_needs_both_to_listen(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    pet_table: PetTable,
    inbox: Inbox,
    clock: ManualClock,
    settings: Settings,
    album_id: int,
) -> None:
    pet_table.reset()

    chosen = await alice.put("/api/quest/album", json={"album_id": album_id}, headers=WRITE)

    assert chosen.status_code == 200, chosen.text
    quest = chosen.json()["quest"]
    assert (quest["kind"], quest["album"]["id"], quest["picked_by"]) == (
        "same_album",
        album_id,
        "alice",
    )
    assert [user for user, message in inbox.messages if "выбрал альбом дня" in message.title] == [
        "bob"
    ]
    tracks = catalog_rows(
        settings,
        "SELECT id, dur FROM tracks WHERE album_id=? AND status='ok' ORDER BY id",
        (album_id,),
    )
    need, t0 = quest["album"]["need"], clock.ms
    for i, (tid, dur) in enumerate(tracks[:need]):
        await bob.post("/api/plays", json=play(tid, (dur or 60) * 1000, t0 + i), headers=WRITE)
    first, first_dur = tracks[0]
    await alice.post("/api/plays", json=play(first, (first_dur or 60) * 1000, t0), headers=WRITE)
    quest = (await bob.get("/api/pet")).json()["quest"]
    assert {part["user"]: part["progress"] for part in quest["parts"]} == {
        "bob": need,
        "alice": min(1, need),
    }
    assert quest["done"] is (need <= 1)
    for i, (tid, dur) in enumerate(tracks[:need]):
        await alice.post(
            "/api/plays", json=play(tid, (dur or 60) * 1000, t0 + 100 + i), headers=WRITE
        )
    assert (await bob.get("/api/pet")).json()["quest"]["done"] is True
    again = await bob.put("/api/quest/album", json={"album_id": album_id}, headers=WRITE)
    assert (again.status_code, again.json()) == (409, {"detail": "done"})
    missing = await alice.put("/api/quest/album", json={"album_id": -1}, headers=WRITE)
    assert (missing.status_code, missing.json()) == (404, {"detail": "no album"})


async def test_the_chosen_album_is_pushed_to_the_partner_tagged_with_the_day(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    pet_table: PetTable,
    inbox: Inbox,
    clock: ManualClock,
    album_id: int,
) -> None:
    clock.ms = noon_ms(SHARED_LIKE_DAY)
    pet_table.reset()

    chosen = await bob.put("/api/quest/album", json={"album_id": album_id}, headers=WRITE)
    refused = await alice.put("/api/quest/album", json={"album_id": -1}, headers=WRITE)

    album = chosen.json()["quest"]["album"]
    assert refused.status_code == 404
    assert inbox.messages == [
        (
            "alice",
            PushMessage(
                "🐻 Мишка выбрал альбом дня",
                f"Слушаем вместе\n🎵 {album['name']} · {album['artist']}",
                "/us",
                "quest-2026-01-18",
            ),
        )
    ]


async def test_a_partner_may_swap_the_album_until_the_quest_is_done(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    pet_table: PetTable,
    settings: Settings,
    album_id: int,
) -> None:
    pet_table.reset()
    other = catalog_ids(
        settings,
        f"SELECT album_id FROM tracks WHERE status='ok' AND album_id<>{album_id} ORDER BY id LIMIT 1",
    )[0]

    await alice.put("/api/quest/album", json={"album_id": album_id}, headers=WRITE)
    swapped = await bob.put("/api/quest/album", json={"album_id": other}, headers=WRITE)

    quest = swapped.json()["quest"]
    assert (quest["album"]["id"], quest["picked_by"]) == (other, "bob")
    assert (await alice.get("/api/pet")).json()["quest"]["album"]["id"] == other
