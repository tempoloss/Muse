import json
from collections import Counter
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx
import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.daily.domain import Ask, Listening, daily_pool
from muse.daily.service import DailyMaker
from muse.discovery.service import RadioModels
from muse.identity.domain import Users
from muse.settings import Settings
from tests.server.support import ORIGIN, ManualClock, ManualClockProvider

NOW_MS = 1_800_000_000_000
DAY = date(2026, 1, 15)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[ManualClockProvider(ManualClock(NOW_MS))])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


async def first_pool(app: Litestar) -> list[dict[str, Any]]:
    container = app.state.dishka_container
    users = await container.get(Users)
    model = await (await container.get(RadioModels)).current()
    nobody = Listening({u.id: [] for u in users.all}, {u.id: {} for u in users.all}, set())
    return daily_pool(DAY, model, users.all, nobody)


async def make(app: Litestar, day: date, ask: Ask) -> bool:
    async with app.state.dishka_container() as request:
        maker = await request.get(DailyMaker)
        return await maker.make(day, ask)


def shown(listing: dict[str, Any]) -> list[tuple[str, str]]:
    return [(item["for"], item["title"]) for item in listing["playlists"]]


async def test_daily_playlists_keep_only_real_tracks_from_the_pool(
    app: Litestar, alice: httpx.AsyncClient, bob: httpx.AsyncClient
) -> None:
    seen: set[str] = set()
    picks: list[int] = []
    for item in await first_pool(app):
        if item["artist"] not in seen:
            seen.add(item["artist"])
            picks.append(item["id"])
    assert len(picks) >= 60
    reply = json.dumps(
        {
            "playlists": [
                {
                    "for": "alice",
                    "title": "Утро",
                    "blurb": "бодро",
                    "tracks": [*picks[:20], 999999999, "x", picks[0]],
                },
                {"for": "Боб", "title": "Вечер", "blurb": "тихо", "tracks": picks[20:40]},
                {"for": "both", "title": "Вдвоём", "blurb": "", "tracks": picks[40:54]},
                {"for": "both", "title": "вдвоём", "tracks": picks[:20]},
                {"for": "alice", "title": "Мало", "tracks": picks[54:60]},
            ]
        },
        ensure_ascii=False,
    )
    prompts: list[str] = []

    async def ask(prompt: str) -> AsyncIterator[tuple[str, str]]:
        prompts.append(prompt)
        yield "broken", "не JSON"
        yield "test-model", f"```json\n{reply}\n```"

    assert await make(app, DAY, ask)

    assert f"\n{picks[0]}|" in prompts[0]
    mine = (await alice.get("/api/daily")).json()
    assert mine["day"] == DAY.isoformat()
    assert shown(mine) == [("alice", "Утро"), ("both", "Вдвоём"), ("bob", "Вечер")]
    assert shown((await bob.get("/api/daily")).json()) == [
        ("bob", "Вечер"),
        ("both", "Вдвоём"),
        ("alice", "Утро"),
    ]
    lists = {
        item["title"]: (await alice.get(f"/api/daily/{item['id']}")).json()
        for item in mine["playlists"]
    }
    assert [item["id"] for item in lists["Утро"]["tracks"]][:20] == picks[:20]
    assert len(lists["Вдвоём"]["tracks"]) > 14
    for listing in lists.values():
        ids = [item["id"] for item in listing["tracks"]]
        assert len(ids) == len(set(ids)) <= 30
        assert max(Counter(item["artist"] for item in listing["tracks"]).values()) <= 3
    assert {item["id"]: item["tracks"] for item in mine["playlists"]} == {
        listing["id"]: len(listing["tracks"]) for listing in lists.values()
    }

    async def unusable(_prompt: str) -> AsyncIterator[tuple[str, str]]:
        yield "m", '{"playlists": [{"title": "x", "tracks": [1, 2]}]}'

    assert not await make(app, date(2026, 1, 16), unusable)
    assert (await bob.get("/api/daily")).json()["day"] == DAY.isoformat()
    missing = await alice.get("/api/daily/999999")
    assert (missing.status_code, missing.json()) == (404, {"detail": "no playlist"})


async def test_without_any_set_the_daily_listing_is_empty(alice: httpx.AsyncClient) -> None:
    assert (await alice.get("/api/daily")).json() == {"day": None, "playlists": []}
