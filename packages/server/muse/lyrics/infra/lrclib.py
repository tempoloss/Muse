from collections.abc import Mapping
from typing import Any

import httpx

from muse.lyrics.domain import (
    LRCLIB,
    TIMEOUT_S,
    USER_AGENT,
    LyricsView,
    Record,
    UnreachableError,
    lyrics_of,
    pick,
)

TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL)
HEADS = {"User-Agent": USER_AGENT}
OK = 200
UNKNOWN = frozenset({400, 404})


class Lrclib:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def ask(self, path: str, params: Mapping[str, str | int | float]) -> Any:
        try:
            response = await self.client.get(
                f"{LRCLIB}{path}", params=params, headers=HEADS, timeout=TIMEOUT_S
            )
        except TRANSPORT_ERRORS as error:
            raise UnreachableError() from error
        if response.status_code in UNKNOWN:
            return None
        if response.status_code != OK:
            raise UnreachableError()
        try:
            return response.json()
        except ValueError as error:
            raise UnreachableError() from error

    async def find(
        self, artist: str, title: str, album: str | None, duration: float | None
    ) -> LyricsView:
        exact: dict[str, str | int | float] = {"artist_name": artist, "track_name": title}
        if album:
            exact["album_name"] = album
        if duration is not None:
            exact["duration"] = round(duration)
        found = await self.ask("/api/get", exact)
        if found is not None:
            return lyrics_of(record_of(found))
        query: dict[str, str | int | float] = {"artist_name": artist, "track_name": title}
        listed = await self.ask("/api/search", query)
        records = [
            record
            for item in (listed if isinstance(listed, list) else [])
            if (record := record_of(item))
        ]
        return lyrics_of(pick(records, duration))


def record_of(item: Any) -> Record | None:
    if not isinstance(item, dict):
        return None
    return Record(
        duration=number(item.get("duration")),
        instrumental=bool(item.get("instrumental")),
        plain=text_of(item.get("plainLyrics")),
        synced=text_of(item.get("syncedLyrics")),
    )


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def text_of(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
