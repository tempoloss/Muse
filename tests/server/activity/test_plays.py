import sqlite3
from contextlib import closing
from typing import Any

import httpx
import pytest

from muse.activity.domain import SOURCE_RE, PlayRecorded, reached_now
from muse.settings import Settings
from muse.shared.events import Event
from tests.server.activity.support import NOW_MS, catalog_row
from tests.server.support import WRITE


def report(track_id: int, listened_ms: int, **fields: Any) -> dict[str, Any]:
    return {
        "track_id": track_id,
        "started_at": NOW_MS - 5000,
        "listened_ms": listened_ms,
        "completed": False,
        "skipped": False,
        "source": "other",
        **fields,
    }


def stored(settings: Settings) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        return db.execute("SELECT * FROM plays ORDER BY user, started_at").fetchall()


async def test_reports_need_an_allowed_origin_and_a_retry_replaces_its_shorter_copy(
    alice: httpx.AsyncClient, settings: Settings, long_track: tuple[int, int]
) -> None:
    tid, dur = long_track

    no_origin = await alice.post("/api/plays", json={})
    too_long = await alice.post("/api/plays", json=report(tid, dur * 1000 + 120000), headers=WRITE)
    first = await alice.post("/api/plays", json=report(tid, 6000), headers=WRITE)
    retry = await alice.post(
        "/api/plays", json=report(tid, 9000, completed=True, source="album:3"), headers=WRITE
    )

    assert (no_origin.status_code, no_origin.json()) == (403, {"detail": "bad origin"})
    assert (too_long.status_code, too_long.json()) == (422, {"detail": "listened_ms out of range"})
    assert (first.status_code, retry.status_code) == (204, 204)
    assert stored(settings) == [("alice", tid, NOW_MS - 5000, 9000, 1, 0, "album:3")]


async def test_the_track_is_checked_before_the_duration_and_the_duration_before_the_source(
    alice: httpx.AsyncClient, settings: Settings, long_track: tuple[int, int]
) -> None:
    tid, dur = long_track
    pending = catalog_row(
        settings.paths.catalog_db, "SELECT id, dur FROM tracks WHERE status<>'ok' LIMIT 1"
    )[0]
    cases = [
        (report(999999999, -1, source="bogus"), (404, "no track")),
        (report(pending, 0), (404, "no track")),
        (report(tid, -1, source="bogus"), (422, "listened_ms out of range")),
        (report(tid, dur * 1000 + 60001), (422, "listened_ms out of range")),
        (report(tid, dur * 1000 + 60000, source="bogus"), (422, "bad source")),
    ]

    for body, expected in cases:
        response = await alice.post("/api/plays", json=body, headers=WRITE)
        assert (response.status_code, response.json()["detail"]) == expected
    assert stored(settings) == []


async def test_a_malformed_report_is_a_422_list(alice: httpx.AsyncClient) -> None:
    response = await alice.post("/api/plays", json={"track_id": 1}, headers=WRITE)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


async def test_a_play_reaches_the_counted_threshold_once(
    alice: httpx.AsyncClient, long_track: tuple[int, int], events: list[Event]
) -> None:
    tid, _ = long_track
    for listened in (10000, 30000, 45000):
        response = await alice.post("/api/plays", json=report(tid, listened), headers=WRITE)
        assert response.status_code == 204

    assert events == [
        PlayRecorded("alice", tid, NOW_MS, reached_now=False),
        PlayRecorded("alice", tid, NOW_MS, reached_now=True),
        PlayRecorded("alice", tid, NOW_MS, reached_now=False),
    ]


@pytest.mark.parametrize(
    ("listened", "previous", "duration", "reached"),
    [
        (30000, None, 300, True),
        (29999, None, 300, False),
        (30000, 29999, 300, True),
        (40000, 30000, 300, False),
        (20000, None, 40, True),
        (19999, None, 40, False),
        (0, None, 0, True),
        (0, 0, 0, False),
    ],
)
def test_the_threshold_is_30_seconds_or_half_a_short_track(
    listened: int, previous: int | None, duration: int, reached: bool
) -> None:
    assert reached_now(listened, previous, duration) is reached


@pytest.mark.parametrize(
    "source",
    [
        "album:12",
        "playlist:Вечер у моря",
        "mix:RU Rap",
        "genre:Indie",
        "daily:7",
        "search",
        "home",
        "artist:Kiro Delta & Wexa",
        "liked",
        "other",
        "ours",
        "radio",
        "together",
        "playlist:" + "x" * 200,
    ],
)
def test_known_sources(source: str) -> None:
    assert SOURCE_RE.fullmatch(source)


@pytest.mark.parametrize(
    "source",
    [
        "",
        "album:",
        "album:x",
        "daily:",
        "Search",
        "homepage",
        "playlist:" + "x" * 201,
        "mix:" + "x" * 101,
    ],
)
def test_unknown_sources(source: str) -> None:
    assert SOURCE_RE.fullmatch(source) is None
