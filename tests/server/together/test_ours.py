import httpx

from muse.notifications.infra.sender import RecordingSender
from tests.server.support import WRITE, ManualClock

type Client = httpx.AsyncClient


async def test_our_playlist_is_shared_and_announces_only_new_tracks(
    alice: Client, bob: Client, track_id: int, pushes: RecordingSender, clock: ManualClock
) -> None:
    track = (await alice.get(f"/api/track/{track_id}")).json()

    for _ in range(2):
        assert (await alice.put(f"/api/ours/{track_id}", headers=WRITE)).status_code == 204

    assert pushes.sent == [
        (
            "bob",
            "🦊 Лисёнок добавил в наш плейлист",
            f"🎵 {track['title']} · {track['artist']}",
            "/ours",
        )
    ]
    assert (await bob.get("/api/ours")).json()["tracks"] == [
        {**track, "added_by": "alice", "added_at": clock.ms}
    ]
    played = await bob.post(
        "/api/plays",
        headers=WRITE,
        json={
            "track_id": track_id,
            "started_at": clock.ms,
            "listened_ms": 40000,
            "completed": False,
            "skipped": False,
            "source": "ours",
        },
    )
    assert played.status_code == 204
    assert (await bob.delete(f"/api/ours/{track_id}", headers=WRITE)).status_code == 204
    assert (await alice.get("/api/ours")).json() == {"tracks": [], "albums": []}


async def test_the_newest_addition_comes_first(
    alice: Client, bob: Client, track_id: int, other_track_id: int, clock: ManualClock
) -> None:
    await alice.put(f"/api/ours/{track_id}", headers=WRITE)
    clock.ms += 1_000
    await bob.put(f"/api/ours/{other_track_id}", headers=WRITE)

    tracks = (await alice.get("/api/ours")).json()["tracks"]

    assert [(item["id"], item["added_by"]) for item in tracks] == [
        (other_track_id, "bob"),
        (track_id, "alice"),
    ]


async def test_only_playable_tracks_join_our_playlist(alice: Client) -> None:
    response = await alice.put("/api/ours/999999", headers=WRITE)

    assert (response.status_code, response.json()) == (404, {"detail": "no track"})
    assert (await alice.get("/api/ours")).json()["tracks"] == []
