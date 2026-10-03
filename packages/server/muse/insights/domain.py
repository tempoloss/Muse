from collections.abc import Callable, Iterable
from typing import Protocol, TypedDict

from muse.catalog.domain import Track

DAY_MS = 86400 * 1000
WHO = ("me", "partner")
TOP_ARTISTS = 10
COMMON_ARTISTS = 5
BAD_WHO = "bad who"


class ArtistPlays(TypedDict):
    name: str
    plays: int


class CommonArtist(TypedDict):
    name: str
    me: int
    partner: int


class TopTrack(Track):
    plays: int


class SharedSong(Track):
    me: int
    partner: int


class LetterCounts(TypedDict):
    me: int
    partner: int


class StatsSummary(TypedDict):
    plays: int
    minutes: int
    top_artists: list[ArtistPlays]
    top_tracks: list[TopTrack]
    by_hour: list[int]


class UsStats(TypedDict):
    together_minutes: int
    both_likes: int
    ours: int
    letters: LetterCounts
    common_artists: list[CommonArtist]
    song: SharedSong | None


def hours_histogram(starts: Iterable[int], hour_of: Callable[[int], int]) -> list[int]:
    hours = [0] * 24
    for started_at in starts:
        hours[hour_of(started_at)] += 1
    return hours


def common_artists(mine: dict[str, int], theirs: dict[str, int]) -> list[CommonArtist]:
    shared = [
        (name, plays, theirs[name]) for name, plays in mine.items() if plays and theirs.get(name)
    ]
    shared.sort(
        key=lambda artist: (-min(artist[1], artist[2]), -(artist[1] + artist[2]), artist[0])
    )
    return [
        {"name": name, "me": me, "partner": partner}
        for name, me, partner in shared[:COMMON_ARTISTS]
    ]


class PlayStats(Protocol):
    async def totals(self, user_id: str, since_ms: int) -> tuple[int, int]: ...

    async def top_tracks(self, user_id: str, since_ms: int) -> list[tuple[int, int]]: ...

    async def play_starts(self, user_id: str, since_ms: int) -> list[int]: ...

    async def top_artists(self, user_id: str, since_ms: int, limit: int) -> list[ArtistPlays]: ...

    async def artist_plays(self, user_id: str, since_ms: int) -> dict[str, int]: ...

    async def shared_songs(
        self, user_id: str, partner_id: str, since_ms: int
    ) -> list[tuple[int, int, int]]: ...

    async def together_seconds(self, since_day: str) -> float: ...

    async def both_likes(self, user_id: str, partner_id: str) -> int: ...

    async def ours(self) -> int: ...

    async def letters_sent(self, user_id: str, since_ms: int) -> int: ...
