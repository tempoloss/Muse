import httpx

from muse.activity.domain import LikeChanged
from muse.shared.events import Event
from tests.server.support import WRITE, ManualClock


async def test_both_like_and_each_sees_the_partners_likes_newest_first(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    clock: ManualClock,
    long_track: tuple[int, int],
    other_track: int,
) -> None:
    tid = long_track[0]
    for client, track in ((alice, tid), (bob, tid), (alice, other_track)):
        clock.ms += 1000
        assert (await client.put(f"/api/likes/{track}", headers=WRITE)).status_code == 204

    assert (await alice.get("/api/likes")).json() == {"me": [other_track, tid], "partner": [tid]}
    assert (await bob.get("/api/likes")).json() == {"me": [tid], "partner": [other_track, tid]}

    assert (await bob.delete(f"/api/likes/{tid}", headers=WRITE)).status_code == 204
    assert (await alice.get("/api/likes")).json()["partner"] == []


async def test_liking_an_unknown_track_is_404_and_unliking_anything_is_204(
    alice: httpx.AsyncClient,
) -> None:
    unknown = await alice.put("/api/likes/999999999", headers=WRITE)
    unlike = await alice.delete("/api/likes/999999999", headers=WRITE)

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "no track"})
    assert unlike.status_code == 204
    assert (await alice.get("/api/likes")).json() == {"me": [], "partner": []}


async def test_only_the_like_that_completes_a_pair_is_a_new_mutual_like(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    long_track: tuple[int, int],
    events: list[Event],
) -> None:
    tid = long_track[0]
    await alice.put(f"/api/likes/{tid}", headers=WRITE)
    await bob.put(f"/api/likes/{tid}", headers=WRITE)
    await bob.put(f"/api/likes/{tid}", headers=WRITE)
    await bob.delete(f"/api/likes/{tid}", headers=WRITE)
    await bob.put(f"/api/likes/{tid}", headers=WRITE)

    assert events == [
        LikeChanged("alice", tid, liked=True, mutual_new=False),
        LikeChanged("bob", tid, liked=True, mutual_new=True),
        LikeChanged("bob", tid, liked=True, mutual_new=False),
        LikeChanged("bob", tid, liked=False, mutual_new=False),
        LikeChanged("bob", tid, liked=True, mutual_new=True),
    ]
