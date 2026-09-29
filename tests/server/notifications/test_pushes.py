import sqlite3
from contextlib import closing

import httpx
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.notifications.infra.sender import RecordingSender
from muse.settings import Settings
from tests.server.support import ORIGIN, WRITE, Inbox, InboxProvider, signed_in


def playable(settings: Settings) -> int:
    uri = f"file:{settings.paths.catalog_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        row = db.execute("SELECT id FROM tracks WHERE status='ok' ORDER BY id LIMIT 1").fetchone()
    return row[0]


async def test_the_like_that_completes_a_pair_pushes_the_partner_once(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, pushes: RecordingSender, settings: Settings
) -> None:
    tid = playable(settings)
    track = (await alice.get(f"/api/track/{tid}")).json()

    await alice.put(f"/api/likes/{tid}", headers=WRITE)
    assert pushes.sent == []
    await bob.put(f"/api/likes/{tid}", headers=WRITE)
    await bob.put(f"/api/likes/{tid}", headers=WRITE)

    assert pushes.sent == [
        (
            "alice",
            "🦊🐻 Совпало!",
            f"Теперь нам обоим нравится\n🎵 {track['title']} · {track['artist']}",
            "/us",
        )
    ]


async def test_unliking_never_pushes(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, pushes: RecordingSender, settings: Settings
) -> None:
    tid = playable(settings)
    await alice.put(f"/api/likes/{tid}", headers=WRITE)
    await alice.delete(f"/api/likes/{tid}", headers=WRITE)
    await bob.put(f"/api/likes/{tid}", headers=WRITE)

    assert pushes.sent == []


async def test_a_mutual_like_push_is_tagged_with_the_track(settings: Settings) -> None:
    tid = playable(settings)
    inbox = Inbox()
    app = create_app(settings, providers=[InboxProvider(inbox)])
    async with AsyncTestClient(app=app, base_url=ORIGIN):
        for login in ("alice", "bob"):
            client = await signed_in(app, login)
            await client.put(f"/api/likes/{tid}", headers=WRITE)
            await client.aclose()

    assert [(user, message.url, message.tag) for user, message in inbox.messages] == [
        ("alice", "/us", f"like-{tid}")
    ]
