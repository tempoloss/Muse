import random
from collections.abc import Iterable, Sequence
from datetime import date
from typing import NotRequired, Protocol, TypedDict

from muse.catalog.domain import AlbumCard, Track
from muse.insights.domain import ArtistPlays

HOME_TTL_S = 120
CONTINUE_LIMIT = 6
RECENT_LIMIT = 20
PARTNER_RECENT_LIMIT = 10
MIX_LIMIT = 6
FORGOTTEN_LIMIT = 10
FORGOTTEN_MIN_TRACKS = 3
DAY_MS = 86_400_000
MIX_WINDOW_MS = 90 * DAY_MS
FORGOTTEN_WINDOW_MS = 60 * DAY_MS
TOP_ARTISTS_WINDOW_MS = 30 * DAY_MS
OTHER_GENRE = "Other"


class ContinueCard(TypedDict):
    kind: str
    title: str
    subtitle: str
    albums: list[int]
    album_id: NotRequired[int]
    name: NotRequired[str]
    genre: NotRequired[str]
    id: NotRequired[int]


class MixCard(TypedDict):
    genre: str
    title: str
    tracks: int
    albums: list[int]


HomeView = TypedDict(
    "HomeView",
    {
        "continue": list[ContinueCard],
        "recent": list[Track],
        "top_artists": list[ArtistPlays],
        "mixes": list[MixCard],
        "forgotten": list[AlbumCard],
        "both_like": list[Track],
        "partner_recent": list[Track],
    },
)


def home_key(user_id: str, day: date) -> str:
    return f"user:{user_id}:home:{day.isoformat()}"


def mix_genres(ranked: Iterable[str], genres: Sequence[str]) -> list[str]:
    names = [genre for genre in ranked if genre in genres and genre != OTHER_GENRE]
    names += [genre for genre in genres if genre != OTHER_GENRE and genre not in names]
    return names[:MIX_LIMIT]


def forgotten_albums(
    albums: Sequence[AlbumCard], heard: set[int], user_id: str, day: date
) -> list[AlbumCard]:
    pool = [
        album
        for album in albums
        if album["ntracks"] >= FORGOTTEN_MIN_TRACKS and album["id"] not in heard
    ]
    return random.Random(f"{user_id}:{day}").sample(pool, min(FORGOTTEN_LIMIT, len(pool)))


class HomeQueries(Protocol):
    async def recent_sources(self, user_id: str) -> list[str]: ...

    async def recent_track_ids(self, user_id: str, limit: int) -> list[int]: ...

    async def both_liked(self, user_id: str, partner_id: str) -> list[int]: ...

    async def genre_ranking(self, user_id: str, since_ms: int) -> list[str]: ...

    async def heard_albums(self, user_id: str, since_ms: int) -> set[int]: ...
