from dataclasses import dataclass
from typing import Any, Protocol

from muse.shared.events import Event

LIVE_FRESH_MS = 45000
FOLLOW_WAIT_S = 25
FOLLOW_TTL_MS = 40000
FOLLOW_POLL_S = 0.25
SHARED_STEP_MS = 30000
PARTNER_FOLLOWS = "partner follows you"

type Track = dict[str, Any]


@dataclass(frozen=True, slots=True)
class TogetherAccrued(Event):
    seconds_before: float
    seconds_after: float


@dataclass(frozen=True, slots=True)
class Beat:
    track_id: int | None
    position: float
    playing: bool
    at: int


def fresh(beat: Beat | None, now: int) -> bool:
    return bool(
        beat and beat.playing and beat.track_id is not None and now - beat.at <= LIVE_FRESH_MS
    )


def follows(started_at: int | None, now: int) -> bool:
    return now - (started_at or 0) <= FOLLOW_TTL_MS


def shared_seconds(previous: Beat | None, current: Beat, partner: Beat | None) -> float | None:
    if not (
        current.playing
        and current.track_id is not None
        and fresh(partner, current.at)
        and previous
        and previous.playing
    ):
        return None
    return min(current.at - previous.at, SHARED_STEP_MS) / 1000 / 2


def clamped(position: float, track: Track) -> float:
    return min(position, track["dur"]) if track["dur"] else position


def live_partner(beat: Beat, track: Track, now: int, following: bool) -> dict[str, Any]:
    position = beat.position + (now - beat.at) / 1000
    return {
        "track": track,
        "position": clamped(position, track),
        "playing": True,
        "following": following,
    }


def mirrored_track_id(beat: Beat | None, now: int) -> int | None:
    if not beat or beat.track_id is None or (beat.playing and now - beat.at > LIVE_FRESH_MS):
        return None
    return beat.track_id


def mirror(beat: Beat, track: Track, now: int) -> dict[str, Any]:
    position = beat.position + ((now - beat.at) / 1000 if beat.playing else 0)
    return {
        "track": track,
        "position": clamped(position, track),
        "playing": beat.playing,
        "at": beat.at,
    }


class LiveBoard(Protocol):
    def report(
        self, user_id: str, partner_id: str, beat: Beat
    ) -> tuple[Beat | None, Beat | None]: ...

    def beat_of(self, user_id: str) -> Beat | None: ...

    def partner_state(self, partner_id: str, now: int) -> tuple[Beat | None, bool]: ...

    def start_following(self, user_id: str, partner_id: str, now: int) -> bool: ...

    def stop_following(self, user_id: str) -> None: ...

    def together_now(self, now_ms: int) -> bool: ...


class TogetherLedger(Protocol):
    async def accrue(self, day: str, seconds: float) -> float: ...


class LetterBox(Protocol):
    async def unread(self, user_id: str) -> int: ...
