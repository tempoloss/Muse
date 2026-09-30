import sqlite3
from contextlib import closing

import httpx
import pytest

from muse.notifications.infra.sender import RecordingSender
from muse.settings import Settings
from tests.server.support import WRITE, ManualClock

type Client = httpx.AsyncClient

TITLES = {
    "🐻 Мишка принёс записку",
    "🐻 Мишка прибежал с запиской",
    "🐻 Мишка оставил тебе записку",
}


async def write_letter(client: Client, track_id: int, text: str) -> httpx.Response:
    return await client.post(
        "/api/letters", headers=WRITE, json={"track_id": track_id, "text": text}
    )


async def test_a_letter_reaches_the_partner_and_is_read_by_them_only_once(
    alice: Client, bob: Client, track_id: int, pushes: RecordingSender, clock: ManualClock
) -> None:
    track = (await alice.get(f"/api/track/{track_id}")).json()

    sent = await write_letter(bob, track_id, "  привет  ")
    blank = await write_letter(bob, track_id, "   ")

    assert sent.status_code == 201, sent.text
    letter_id = sent.json()["id"]
    assert (blank.status_code, blank.json()) == (422, {"detail": "bad text"})
    assert (await alice.get("/api/letters")).json()["received"] == [
        {
            "id": letter_id,
            "from": "bob",
            "to": "alice",
            "track": track,
            "text": "привет",
            "created_at": clock.ms,
            "read_at": None,
        }
    ]
    assert (await alice.get("/api/live")).json()["unread"] == 1
    assert (await bob.post(f"/api/letters/{letter_id}/read", headers=WRITE)).status_code == 404
    clock.ms += 1_000
    read_at = clock.ms
    assert (await alice.post(f"/api/letters/{letter_id}/read", headers=WRITE)).status_code == 204
    clock.ms += 1_000
    assert (await alice.post(f"/api/letters/{letter_id}/read", headers=WRITE)).status_code == 204
    assert (await alice.get("/api/live")).json()["unread"] == 0
    assert (await alice.get("/api/letters")).json()["received"][0]["read_at"] == read_at
    assert [item["id"] for item in (await bob.get("/api/letters")).json()["sent"]] == [letter_id]

    [(user, title, body, url)] = pushes.sent
    assert (user, url) == ("alice", "/?letters=1")
    assert title in TITLES
    assert body == f"привет\n🎵 {track['title']} · {track['artist']}"


async def test_a_letter_is_a_gift_for_the_pet(
    alice: Client, track_id: int, settings: Settings, clock: ManualClock
) -> None:
    with closing(sqlite3.connect(settings.paths.user_db)) as db, db:
        db.execute("UPDATE pet SET joy=50, updated_at=?", (clock.ms,))

    letter_id = (await write_letter(alice, track_id, "for you")).json()["id"]

    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        joy = db.execute("SELECT joy FROM pet").fetchone()[0]
        log = db.execute("SELECT at, user, action, detail FROM pet_log").fetchall()
    assert joy == 65
    assert log == [(clock.ms, "alice", "gift", str(letter_id))]


@pytest.mark.parametrize("text", ["", "x" * 281])
async def test_letters_hold_one_to_280_characters(
    alice: Client, track_id: int, text: str, pushes: RecordingSender
) -> None:
    assert (await write_letter(alice, track_id, text)).status_code == 422
    assert (await write_letter(alice, track_id, " " + "x" * 280 + " ")).status_code == 201
    [(_, _, body, _)] = pushes.sent
    assert body.startswith("x" * 120 + "\n🎵 ")


async def test_a_letter_needs_its_text_first_and_then_a_playable_track(
    alice: Client, bob: Client
) -> None:
    unwritten = await write_letter(alice, 999_999, "   ")
    unknown = await write_letter(alice, 999_999, "hi")

    assert (unwritten.status_code, unwritten.json()) == (422, {"detail": "bad text"})
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "no track"})
    assert (await bob.get("/api/letters")).json() == {"received": [], "sent": []}


async def test_letters_list_the_newest_hundred_each_way(
    alice: Client, settings: Settings, track_id: int
) -> None:
    with closing(sqlite3.connect(settings.paths.user_db)) as db, db:
        db.executemany(
            "INSERT INTO letters(sender, recipient, track_id, text, created_at) "
            "VALUES ('bob', 'alice', ?, ?, ?)",
            [(track_id, f"n{index}", 1_000 + index // 2) for index in range(101)],
        )

    received = (await alice.get("/api/letters")).json()["received"]

    assert [letter["text"] for letter in received] == [f"n{index}" for index in range(100, 0, -1)]
