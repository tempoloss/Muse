import re
from dataclasses import dataclass
from typing import Protocol

from muse.catalog.domain import ARTIST
from muse.shared.events import Event

COUNTED = "p.listened_ms >= MIN(30000, lib_t.dur*500)"
PLAYS_LIB = "FROM plays p JOIN lib.tracks lib_t ON lib_t.id=p.track_id "
PLAY_ARTIST = ARTIST.replace("t.artist", "lib_t.artist")
SOURCE_RE = re.compile(
    r"album:\d+|playlist:.{1,200}|mix:.{1,100}|genre:.{1,100}|daily:\d+|search|home|artist:.{1,200}|liked|other|ours|radio|together"
)
COUNTED_MS = 30000
COUNTED_SHARE_MS = 500
LISTEN_SLACK_MS = 60000
LISTENED_OUT_OF_RANGE = "listened_ms out of range"
BAD_SOURCE = "bad source"


@dataclass(frozen=True, slots=True)
class Play:
    track_id: int
    started_at: int
    listened_ms: int
    completed: bool
    skipped: bool
    source: str


@dataclass(frozen=True, slots=True)
class PlayRecorded(Event):
    user: str
    track_id: int
    at: int
    reached_now: bool


@dataclass(frozen=True, slots=True)
class LikeChanged(Event):
    user: str
    track_id: int
    liked: bool
    mutual_new: bool


def counted_ms(duration_s: int) -> int:
    return min(COUNTED_MS, duration_s * COUNTED_SHARE_MS)


def listened_in_range(listened_ms: int, duration_s: int) -> bool:
    return 0 <= listened_ms <= duration_s * 1000 + LISTEN_SLACK_MS


def reached_now(listened_ms: int, previous_ms: int | None, duration_s: int) -> bool:
    need = counted_ms(duration_s)
    return listened_ms >= need and not (previous_ms is not None and previous_ms >= need)


class PlayRepository(Protocol):
    async def lock(self) -> None: ...

    async def listened(self, user: str, track_id: int, started_at: int) -> int | None: ...

    async def save(self, user: str, play: Play) -> None: ...


class LikeRepository(Protocol):
    async def add(self, user: str, track_id: int, at: int) -> bool: ...

    async def has(self, user: str, track_id: int) -> bool: ...

    async def remove(self, user: str, track_id: int) -> None: ...

    async def track_ids(self, user: str) -> list[int]: ...
