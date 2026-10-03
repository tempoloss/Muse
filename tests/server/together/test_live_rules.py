import pytest

from muse.catalog.domain import Track
from muse.identity.domain import User, Users
from muse.together.domain import (
    Beat,
    fresh,
    live_partner,
    mirror,
    mirrored_track_id,
    shared_seconds,
)
from muse.together.infra.live import LiveRegistry

T0 = 1_800_000_000_000
TRACK: Track = {
    "id": 7,
    "num": 1,
    "title": "Song",
    "dur": 200,
    "album_id": 3,
    "album": "A",
    "artist": "B",
}


def playing(at: int, track_id: int | None = 7, position: float = 30.0) -> Beat:
    return Beat(track_id, position, True, at)


def paused(at: int, position: float = 30.0) -> Beat:
    return Beat(7, position, False, at)


@pytest.fixture
def registry() -> LiveRegistry:
    return LiveRegistry(
        Users(
            User("alice", "alice", "A", "fox", "light", "🦊", "Лисёнок"),
            User("bob", "bob", "B", "bear", "dark", "🐻", "Мишка"),
        )
    )


def test_only_a_playing_track_heard_from_within_45_seconds_is_live() -> None:
    assert fresh(playing(T0), T0 + 45_000)
    assert not fresh(playing(T0), T0 + 45_001)
    assert not fresh(paused(T0), T0)
    assert not fresh(playing(T0, track_id=None), T0)
    assert not fresh(None, T0)


def test_shared_listening_counts_half_the_gap_between_beats_capped_at_30_seconds() -> None:
    now = T0 + 10_000

    assert shared_seconds(playing(T0), playing(now), playing(T0)) == 5.0
    assert shared_seconds(playing(T0), playing(T0 + 70_000), playing(T0 + 60_000)) == 15.0


@pytest.mark.parametrize(
    ("previous", "current", "partner"),
    [
        (None, playing(T0 + 10_000), playing(T0)),
        (paused(T0), playing(T0 + 10_000), playing(T0)),
        (playing(T0), paused(T0 + 10_000), playing(T0)),
        (playing(T0), playing(T0 + 10_000, track_id=None), playing(T0)),
        (playing(T0), playing(T0 + 50_000), playing(T0)),
        (playing(T0), playing(T0 + 10_000), paused(T0)),
    ],
)
def test_shared_listening_needs_two_playing_beats_and_a_live_partner(
    previous: Beat | None, current: Beat, partner: Beat
) -> None:
    assert shared_seconds(previous, current, partner) is None


def test_the_partner_position_runs_on_from_the_beat_and_stops_at_the_track_end() -> None:
    assert live_partner(playing(T0), TRACK, T0 + 4_500, following=True) == {
        "track": TRACK,
        "position": 34.5,
        "playing": True,
        "following": True,
    }
    assert live_partner(playing(T0), TRACK, T0 + 400_000, following=False)["position"] == 200
    untimed: Track = {**TRACK, "dur": None}
    assert live_partner(playing(T0), untimed, T0 + 400_000, following=False)["position"] == 430


def test_a_paused_partner_is_mirrored_however_old_and_a_silent_player_is_not() -> None:
    long_ago = T0 - 3_600_000

    assert mirrored_track_id(paused(long_ago, position=31), T0) == 7
    assert mirror(paused(long_ago, position=31), TRACK, T0) == {
        "track": TRACK,
        "position": 31,
        "playing": False,
        "at": long_ago,
    }
    assert mirrored_track_id(playing(T0 - 45_000), T0) == 7
    assert mirrored_track_id(playing(T0 - 45_001), T0) is None
    assert mirrored_track_id(Beat(None, 0.0, False, T0), T0) is None
    assert mirrored_track_id(None, T0) is None


def test_a_beat_replaces_the_previous_one_and_returns_it_with_the_partner_beat(
    registry: LiveRegistry,
) -> None:
    assert registry.report("alice", "bob", playing(T0)) == (None, None)
    registry.report("bob", "alice", paused(T0 + 1))

    previous, partner = registry.report("alice", "bob", playing(T0 + 2))

    assert (previous, partner) == (playing(T0), paused(T0 + 1))
    assert registry.beat_of("alice") == playing(T0 + 2)


def test_following_goes_one_way_until_the_mark_expires_or_is_dropped(
    registry: LiveRegistry,
) -> None:
    assert registry.start_following("alice", "bob", T0)

    assert not registry.start_following("bob", "alice", T0 + 40_000)
    assert registry.partner_state("alice", T0 + 40_000) == (None, True)
    assert registry.start_following("bob", "alice", T0 + 40_001)

    registry.stop_following("bob")
    assert registry.partner_state("bob", T0 + 40_002) == (None, False)
    assert registry.start_following("alice", "bob", T0 + 40_002)


def test_the_partner_state_shows_only_a_live_beat(registry: LiveRegistry) -> None:
    registry.report("bob", "alice", playing(T0))

    assert registry.partner_state("bob", T0 + 45_000) == (playing(T0), False)
    assert registry.partner_state("bob", T0 + 45_001) == (None, False)


def test_together_needs_both_players_live(registry: LiveRegistry) -> None:
    registry.report("alice", "bob", playing(T0))
    assert not registry.together_now(T0)

    registry.report("bob", "alice", playing(T0 + 1_000))

    assert registry.together_now(T0 + 45_000)
    assert not registry.together_now(T0 + 45_001)
