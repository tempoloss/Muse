import sqlite3
from contextlib import closing
from typing import Any

import httpx

from muse.settings import Settings
from tests.server.support import WRITE

ENDPOINT = "https://push.example.org/send/"


def subscription(endpoint: str, p256dh: str = "p256", auth: str = "secret") -> dict[str, Any]:
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def stored(settings: Settings) -> list[tuple[str, str, str, str]]:
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        return db.execute(
            "SELECT endpoint, user, p256dh, auth FROM push_subs ORDER BY endpoint"
        ).fetchall()


async def test_the_key_is_null_while_push_is_disabled(alice: httpx.AsyncClient) -> None:
    assert (await alice.get("/api/push/key")).json() == {"key": None}


async def test_an_endpoint_must_be_https_and_at_most_1000_characters(
    alice: httpx.AsyncClient, settings: Settings
) -> None:
    longest = ENDPOINT + "a" * (1000 - len(ENDPOINT))
    refused = [longest + "a", "http://push.example.org/send/1", "push.example.org"]

    for endpoint in refused:
        response = await alice.post(
            "/api/push/subscribe", json=subscription(endpoint), headers=WRITE
        )
        assert (response.status_code, response.json()) == (422, {"detail": "bad endpoint"})
    accepted = await alice.post("/api/push/subscribe", json=subscription(longest), headers=WRITE)

    assert accepted.status_code == 204
    assert stored(settings) == [(longest, "alice", "p256", "secret")]


async def test_a_phone_that_switches_accounts_moves_its_endpoint(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, settings: Settings
) -> None:
    await alice.post("/api/push/subscribe", json=subscription(ENDPOINT + "1"), headers=WRITE)
    await bob.post(
        "/api/push/subscribe", json=subscription(ENDPOINT + "1", "p2", "a2"), headers=WRITE
    )

    assert stored(settings) == [(ENDPOINT + "1", "bob", "p2", "a2")]


async def test_unsubscribe_removes_only_your_own_endpoint(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, settings: Settings
) -> None:
    await alice.post("/api/push/subscribe", json=subscription(ENDPOINT + "1"), headers=WRITE)
    await bob.post("/api/push/subscribe", json=subscription(ENDPOINT + "2"), headers=WRITE)

    foreign = await alice.post(
        "/api/push/unsubscribe", json={"endpoint": ENDPOINT + "2"}, headers=WRITE
    )
    own = await alice.post(
        "/api/push/unsubscribe", json={"endpoint": ENDPOINT + "1"}, headers=WRITE
    )

    assert (foreign.status_code, own.status_code) == (204, 204)
    assert stored(settings) == [(ENDPOINT + "2", "bob", "p256", "secret")]


async def test_a_subscription_without_keys_is_a_422_list(alice: httpx.AsyncClient) -> None:
    response = await alice.post("/api/push/subscribe", json={"endpoint": ENDPOINT}, headers=WRITE)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
