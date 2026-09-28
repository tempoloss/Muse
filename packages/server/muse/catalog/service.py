from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any

import anyio

from muse.catalog.domain import (
    CATALOG_TTL_S,
    COVER_MOSAIC,
    NO_ALBUM,
    NO_SUCH_ARTIST,
    NO_SUCH_GENRE,
    NO_TRACK,
    SEARCH_MIN_CHARS,
    CatalogQueries,
    LibraryState,
    Row,
    album_name,
    first_albums,
    search_pattern,
)
from muse.shared.cache import Cache
from muse.shared.errors import DomainError


class Catalog:
    def __init__(self, queries: CatalogQueries, library: LibraryState, cache: Cache) -> None:
        self.queries = queries
        self.library = library
        self.cache = cache

    async def fingerprint(self) -> str:
        return await anyio.to_thread.run_sync(self.library.fingerprint)

    async def _cached[T](self, key: str, compute: Callable[[], Awaitable[T]]) -> T:
        fingerprint = await self.fingerprint()
        return await self.cache.get_or_compute(f"lib:{fingerprint}:{key}", CATALOG_TTL_S, compute)

    async def genres(self) -> list[Row]:
        return await self._cached("genres", self.queries.genres)

    async def genre_counts(self) -> dict[str, int]:
        return {row["genre"]: row["tracks"] for row in await self.genres() if row["genre"]}

    async def artists(self, genre: str = "") -> list[Row]:
        key = "artists" + (f":{genre}" if genre else "")
        return await self._cached(key, lambda: self.queries.artists(genre))

    async def artist(self, name: str) -> Row:
        async def compute() -> Row | None:
            rows = await self.queries.artist_albums(name)
            return {"name": name, "genre": rows[0]["genre"], "albums": rows} if rows else None

        data = await self._cached(f"artist:{name}", compute)
        if not data:
            raise DomainError(NO_SUCH_ARTIST)
        return data

    async def albums(self, genre: str = "") -> list[Row]:
        key = "albums" + (f":{genre}" if genre else "")
        return await self._cached(key, lambda: self.queries.albums(genre))

    async def album(self, album_id: int) -> Row:
        found = await self.queries.album(album_id)
        if not found:
            raise DomainError(NO_ALBUM)
        return {
            "id": found["id"],
            "name": album_name(found["name"], found["artist"], found["who"]),
            "year": found["year"],
            "genre": found["genre"],
            "artist": found["who"],
            "cover": f"/api/cover/{album_id}",
            "tracks": await self.queries.album_tracks(album_id),
        }

    async def album_head(self, album_id: int) -> Row | None:
        return await self.queries.album_head(album_id)

    async def search(self, query: str) -> Row:
        if len(query) < SEARCH_MIN_CHARS:
            return {"artists": [], "albums": [], "tracks": []}
        return await self.queries.search(search_pattern(query))

    async def track(self, track_id: int) -> Row:
        found = await self.queries.track(track_id)
        if not found:
            raise DomainError(NO_TRACK)
        return found

    async def genre(self, genre: str) -> Row:
        if genre not in await self.genre_counts():
            raise DomainError(NO_SUCH_GENRE)

        async def compute() -> Row:
            tracks = await self.queries.genre_tracks(genre)
            return {
                "genre": genre,
                "title": genre,
                "tracks": tracks,
                "albums": await self.cover_ids(tracks),
            }

        return await self._cached(f"genre:{genre}", compute)

    async def track_rows(self, ids: Iterable[int]) -> dict[int, Row]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return {}
        return {row["id"]: row for row in await self.queries.track_rows(unique)}

    async def tracks_in_order(self, ids: Sequence[int]) -> list[Row]:
        rows = await self.track_rows(ids)
        return [rows[track_id] for track_id in ids if track_id in rows]

    async def playable_duration(self, track_id: int) -> int:
        found = await self.queries.duration(track_id)
        if not found:
            raise DomainError(NO_TRACK)
        return found["dur"] or 0

    async def cover_ids(
        self, tracks: Iterable[Mapping[str, Any]], limit: int = COVER_MOSAIC
    ) -> list[int]:
        listed = list(tracks)
        album_ids = list(dict.fromkeys(track["album_id"] for track in listed))
        covered = await anyio.to_thread.run_sync(self.library.covered, album_ids)
        return first_albums(listed, covered, limit)

    async def library_tracks(self) -> list[Row]:
        return await self.queries.library_tracks()
