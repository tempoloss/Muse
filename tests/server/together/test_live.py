import sqlite3
from contextlib import closing
from typing import Any

import anyio
import httpx
import pytest

from muse.settings import Settings
from tests.server.support import WRITE, ManualClock

type Client = httpx.AsyncClient


def together_seconds(settings: Settings, day: str) -> float | None:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        row = db.execute("SELECT seconds FROM together WHERE day=?", (day,)).fetchone()
    return row[0] if row else None


def pet_joy(settings: Settings) -> float:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        return db.execute("SELECT joy FROM pet WHERE id=1").fetchone()[0]


async def send_beat(client: Client, track_id: int | None, **changes: object) -> dict[str, Any]:
    beat = {"track_id": track_id, "position": 30, "playing": True, **changes}
    response = await client.post("/api/live", headers=WRITE, json=beat)
    assert response.status_code == 200, response.text
    return response.json()


async def follow(client: Client, query: str = "wait=0") -> httpx.Response:
    return await client.get(f"/api/live/follow?{query}")


async def test_listening_at_once_counts_shared_time_until_the_partner_goes_quiet(
    alice: Client, bob: Client, clock: ManualClock, track_id: int, settings: Settings
) -> None:
    await send_beat(alice, track_id, position=5)
    await send_beat(bob, track_id, position=5)
    clock.ms += 10_000

    view = await send_beat(bob, track_id, position=5)

    assert view == {
        "partner": {
            "track": (await bob.get(f"/api/track/{track_id}")).json(),
            "position": 15,
            "playing": True,
            "following": False,
        },
        "together": True,
        "unread": 0,
    }
    assert together_seconds(settings, clock.today().isoformat()) == 5.0
    clock.ms += 60_000
    assert (await bob.get("/api/live")).json() == {"partner": None, "together": False, "unread": 0}


async def test_shared_time_cheers_the_pet_up_to_forty_points_a_day(
    alice: Client, bob: Client, clock: ManualClock, track_id: int, settings: Settings
) -> None:
    today = clock.today().isoformat()
    without_decay_until = clock.ms + 3_600_000
    with closing(sqlite3.connect(settings.paths.user_db)) as db, db:
        db.execute("UPDATE pet SET joy=50, updated_at=?", (without_decay_until,))
        db.execute("INSERT INTO together(day, seconds) VALUES (?, 2395)", (today,))
    await send_beat(alice, track_id)
    await send_beat(bob, track_id)

    for _ in range(2):
        clock.ms += 10_000
        await send_beat(alice, track_id)

    assert together_seconds(settings, today) == 2405.0
    assert pet_joy(settings) == pytest.approx(50 + 5 / 60)


async def test_the_pet_dances_while_both_listen(
    alice: Client, bob: Client, clock: ManualClock, track_id: int
) -> None:
    await send_beat(alice, track_id)
    await send_beat(bob, track_id)

    dancing = (await alice.get("/api/pet")).json()
    clock.ms += 45_001
    alone = (await alice.get("/api/pet")).json()

    assert (dancing["together_now"], dancing["mood"]) == (True, "dancing")
    assert alone["together_now"] is False


async def test_a_beat_on_an_unknown_track_is_refused_and_not_shown(
    alice: Client, bob: Client
) -> None:
    response = await bob.post(
        "/api/live", headers=WRITE, json={"track_id": 999_999, "position": 1, "playing": True}
    )

    assert (response.status_code, response.json()) == (404, {"detail": "no track"})
    assert (await alice.get("/api/live")).json()["partner"] is None


async def test_the_live_view_counts_the_unread_letters_addressed_to_me(
    alice: Client, bob: Client, settings: Settings, track_id: int
) -> None:
    with closing(sqlite3.connect(settings.paths.user_db)) as db, db:
        db.executemany(
            "INSERT INTO letters(sender, recipient, track_id, text, created_at, read_at) "
            "VALUES (?, ?, ?, 'hi', 1, ?)",
            [("bob", "alice", track_id, None), ("bob", "alice", track_id, 2)]
            + [("alice", "bob", track_id, None)] * 2,
        )

    assert (await alice.get("/api/live")).json()["unread"] == 1
    assert (await bob.get("/api/live")).json()["unread"] == 2


async def test_follow_mirrors_the_partner_one_way(
    alice: Client, bob: Client, clock: ManualClock, track_id: int
) -> None:
    answers: list[httpx.Response] = []

    async def poll(query: str) -> None:
        answers.append(await follow(alice, query))

    await send_beat(bob, track_id)
    partner = (await follow(alice)).json()["partner"]
    assert (partner["track"]["id"], partner["playing"], partner["position"]) == (track_id, True, 30)

    async with anyio.create_task_group() as group:
        group.start_soon(poll, f"since={partner['at']}&wait=10")
        await anyio.sleep(0.5)
        paused_at = anyio.current_time()
        clock.ms += 500
        await send_beat(bob, track_id, position=31, playing=False)
    assert anyio.current_time() - paused_at < 3
    paused = answers[0].json()["partner"]
    assert (paused["playing"], paused["position"], paused["at"]) == (False, 31, clock.ms)

    await send_beat(alice, track_id)
    assert (await bob.get("/api/live")).json()["partner"]["following"] is True
    refused = await follow(bob)
    assert (refused.status_code, refused.json()) == (409, {"detail": "partner follows you"})

    async with anyio.create_task_group() as group:
        group.start_soon(poll, f"since={paused['at']}&wait=2")
        await anyio.sleep(0.3)
        assert (await alice.delete("/api/live/follow", headers=WRITE)).status_code == 204
        assert (await bob.get("/api/live")).json()["partner"]["following"] is False
    assert answers[1].json() == {"partner": paused}

    assert (await follow(bob)).status_code == 200
    assert (await bob.delete("/api/live/follow", headers=WRITE)).status_code == 204
    await send_beat(bob, track_id)
    clock.ms += 45_001
    assert (await follow(alice)).json() == {"partner": None}
    await send_beat(bob, None, playing=False)
    assert (await follow(alice)).json() == {"partner": None}
    assert (await alice.delete("/api/live/follow", headers=WRITE)).status_code == 204
    played = await alice.post(
        "/api/plays",
        headers=WRITE,
        json={
            "track_id": track_id,
            "started_at": clock.ms,
            "listened_ms": 40_000,
            "completed": False,
            "skipped": False,
            "source": "together",
        },
    )
    assert played.status_code == 204


async def test_two_partners_starting_to_follow_at_once_leave_one_refused(
    alice: Client, bob: Client
) -> None:
    statuses: list[int] = []

    async def start(client: Client) -> None:
        statuses.append((await follow(client)).status_code)

    async with anyio.create_task_group() as group:
        group.start_soon(start, alice)
        group.start_soon(start, bob)

    assert sorted(statuses) == [200, 409]


async def test_the_follow_wait_stays_within_25_seconds(
    alice: Client, bob: Client, track_id: int
) -> None:
    await send_beat(bob, track_id)

    accepted = await follow(alice, "wait=25")
    refused = [(await follow(alice, f"wait={wait}")) for wait in ("-1", "25.5")]

    assert accepted.json()["partner"]["track"]["id"] == track_id
    assert [
        (response.status_code, response.json()["detail"][0]["loc"]) for response in refused
    ] == [(422, ["query", "wait"])] * 2
