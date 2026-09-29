from typing import Any

import httpx
import pytest

from muse.notifications.infra.sender import RecordingSender
from muse.settings import Settings
from tests.server.pet.support import DAY_MS, PetTable, catalog_ids
from tests.server.support import WRITE, ManualClock


@pytest.fixture
def tracks(settings: Settings) -> list[int]:
    return catalog_ids(
        settings, "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 2"
    )


def play(track_id: int, listened_ms: int, started_at: int) -> dict[str, Any]:
    return {
        "track_id": track_id,
        "started_at": started_at,
        "listened_ms": listened_ms,
        "completed": False,
        "skipped": False,
        "source": "other",
    }


async def test_music_feeds_once_per_play_and_a_mutual_like_is_a_treat(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    pet_table: PetTable,
    pushes: RecordingSender,
    clock: ManualClock,
    tracks: list[int],
) -> None:
    pet_table.reset(food=50, joy=50, energy=50, clean=50)
    heard, liked = tracks

    first = await bob.post("/api/plays", json=play(heard, 40000, clock.ms + 5000), headers=WRITE)
    fed = pet_table.row()["food"]
    retry = await bob.post("/api/plays", json=play(heard, 45000, clock.ms + 5000), headers=WRITE)
    for client in (alice, bob):
        assert (await client.put(f"/api/likes/{liked}", headers=WRITE)).status_code == 204

    assert (first.status_code, retry.status_code, fed) == (204, 204, 52)
    assert (pet_table.row()["food"], pet_table.row()["joy"]) == (62, 60)
    assert pet_table.log("music") == [("bob", "2")]
    assert pet_table.log("treat") == [("bob", str(liked))]
    assert [push[0] for push in pushes.sent if "Совпало!" in push[1]] == ["alice"]


async def test_music_feeds_at_most_30_food_a_day(
    alice: httpx.AsyncClient, pet_table: PetTable, clock: ManualClock, tracks: list[int]
) -> None:
    pet_table.reset(food=10, joy=50, energy=50, clean=50)

    for minute in range(16):
        await alice.post(
            "/api/plays", json=play(tracks[0], 40000, clock.ms + minute), headers=WRITE
        )
    capped = pet_table.row()["food"]
    clock.ms += DAY_MS
    await alice.post("/api/plays", json=play(tracks[0], 40000, clock.ms), headers=WRITE)

    assert capped == 40
    assert pet_table.log("music") == [("alice", "2")] * 16
