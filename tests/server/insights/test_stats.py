import sqlite3
from contextlib import closing
from datetime import timedelta

import httpx

from muse.settings import Settings
from tests.fixtures.catalog import RENAMED_CANONICAL, RENAMED_TAG, FixtureCatalog
from tests.server.support import WRITE, ManualClock

type Client = httpx.AsyncClient


def track_by(library: FixtureCatalog, artist_tag: str) -> int:
    uri = f"file:{library.catalog_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        sql = "SELECT id FROM tracks WHERE status='ok' AND artist=? ORDER BY id LIMIT 1"
        return db.execute(sql, (artist_tag,)).fetchone()[0]


async def play(client: Client, track_id: int, listened_ms: int, started_at: int) -> None:
    response = await client.post(
        "/api/plays",
        headers=WRITE,
        json={
            "track_id": track_id,
            "started_at": started_at,
            "listened_ms": listened_ms,
            "completed": False,
            "skipped": False,
            "source": "other",
        },
    )
    assert response.status_code == 204, response.text


async def test_only_counted_plays_reach_stats(
    bob: Client, track_id: int, clock: ManualClock
) -> None:
    await play(bob, track_id, 10_000, clock.ms)
    assert (await bob.get("/api/stats?days=1")).json()["plays"] == 0

    await play(bob, track_id, 40_000, clock.ms + 1)
    stats = (await bob.get("/api/stats?days=1")).json()

    assert (stats["plays"], stats["minutes"]) == (1, 0)
    assert [(item["id"], item["plays"]) for item in stats["top_tracks"]] == [(track_id, 1)]
    assert [item["plays"] for item in stats["top_artists"]] == [1]
    assert sum(stats["by_hour"]) == 1
    assert (await bob.get("/api/stats?days=0")).status_code == 422
    assert (await bob.get("/api/stats?days=366")).status_code == 422


async def test_stats_cover_the_last_days_only(
    alice: Client, track_id: int, clock: ManualClock
) -> None:
    day_ms = 86_400_000
    await play(alice, track_id, 60_000, clock.ms - day_ms - 1)
    await play(alice, track_id, 120_000, clock.ms - day_ms)

    one_day = (await alice.get("/api/stats?days=1")).json()
    year = (await alice.get("/api/stats?days=365")).json()

    assert (one_day["plays"], one_day["minutes"]) == (1, 2)
    assert (year["plays"], year["minutes"]) == (2, 3)


async def test_top_tracks_rank_by_plays_then_by_the_latest_play(
    alice: Client, track_id: int, other_track_id: int, clock: ManualClock
) -> None:
    for offset, played in enumerate([track_id, other_track_id, track_id, other_track_id]):
        await play(alice, played, 40_000, clock.ms - 10 + offset)
    tied = (await alice.get("/api/stats")).json()["top_tracks"]
    await play(alice, track_id, 40_000, clock.ms)
    ahead = (await alice.get("/api/stats")).json()["top_tracks"]

    assert [(item["id"], item["plays"]) for item in tied] == [(other_track_id, 2), (track_id, 2)]
    assert [(item["id"], item["plays"]) for item in ahead] == [(track_id, 3), (other_track_id, 2)]


async def test_top_artists_go_by_their_canonical_names_and_most_plays_first(
    alice: Client, library: FixtureCatalog, track_id: int, clock: ManualClock
) -> None:
    renamed = track_by(library, RENAMED_TAG)
    artist = (await alice.get(f"/api/track/{track_id}")).json()["artist"]
    for offset in range(2):
        await play(alice, renamed, 40_000, clock.ms - offset)
    await play(alice, track_id, 40_000, clock.ms - 2)

    top_artists = (await alice.get("/api/stats")).json()["top_artists"]

    assert top_artists == [
        {"name": RENAMED_CANONICAL, "plays": 2},
        {"name": artist, "plays": 1},
    ]


async def test_plays_are_counted_by_the_hour_of_the_configured_timezone(
    alice: Client, track_id: int, clock: ManualClock
) -> None:
    await play(alice, track_id, 40_000, clock.ms)

    by_hour = (await alice.get("/api/stats")).json()["by_hour"]

    assert clock.now().hour == 21
    assert by_hour == [1 if hour == 21 else 0 for hour in range(24)]


async def test_partner_stats_and_our_stats(
    alice: Client, bob: Client, track_id: int, other_track_id: int, clock: ManualClock
) -> None:
    for client in (alice, bob):
        await play(client, track_id, 40_000, clock.ms)
        assert (await client.put(f"/api/likes/{track_id}", headers=WRITE)).status_code == 204
    await play(bob, other_track_id, 40_000, clock.ms + 1)
    await alice.put(f"/api/ours/{other_track_id}", headers=WRITE)
    letter = {"track_id": track_id, "text": "hi"}
    assert (await bob.post("/api/letters", headers=WRITE, json=letter)).status_code == 201

    partner = (await alice.get("/api/stats?who=partner")).json()
    refused = await alice.get("/api/stats?who=x")
    us = (await bob.get("/api/stats/us")).json()

    assert partner == (await bob.get("/api/stats")).json()
    assert (refused.status_code, refused.json()) == (422, {"detail": "bad who"})
    assert set(us) == {
        "together_minutes",
        "both_likes",
        "ours",
        "letters",
        "common_artists",
        "song",
    }
    assert (us["both_likes"], us["ours"], us["letters"]) == (1, 1, {"me": 1, "partner": 0})
    assert (us["song"]["id"], us["song"]["me"], us["song"]["partner"]) == (track_id, 1, 1)
    assert us["common_artists"][0]["name"] == us["song"]["artist"]


async def test_together_minutes_cover_today_and_the_days_before(
    alice: Client, settings: Settings, clock: ManualClock
) -> None:
    today = clock.today()
    with closing(sqlite3.connect(settings.paths.user_db)) as db, db:
        db.executemany(
            "INSERT INTO together(day, seconds) VALUES (?, ?)",
            [
                (today.isoformat(), 125.5),
                ((today - timedelta(days=1)).isoformat(), 600.0),
                ((today - timedelta(days=2)).isoformat(), 6000.0),
            ],
        )

    minutes = [
        (await alice.get(f"/api/stats/us?days={days}")).json()["together_minutes"]
        for days in (1, 2, 3)
    ]

    assert minutes == [2, 12, 112]
