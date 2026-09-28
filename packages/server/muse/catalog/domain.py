from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

type Row = dict[str, Any]

SINGLES = "Одиночные и синглы"
ARTIST = "COALESCE(ar.canonical, t.artist)"
PLAYABLE = (
    "FROM tracks t JOIN albums al ON al.id=t.album_id LEFT JOIN artists ar ON ar.name=t.artist "
    "WHERE t.status='ok' "
)
ALBUM_NAME = (
    "CASE WHEN al.name='Одиночные и синглы' AND al.artist<>"
    + ARTIST.replace("t.artist", "al.artist")
    + " THEN 'Синглы · ' || al.artist ELSE al.name END"
)
TRACK_COLUMNS = f"t.id, t.num, t.title, t.dur, t.album_id, {ALBUM_NAME} album, {ARTIST} artist"
CATALOG_TTL_S = 86400
SEARCH_MIN_CHARS = 2
COVER_MOSAIC = 4
NO_SUCH_ARTIST = "no such artist"
NO_ALBUM = "no album"
NO_TRACK = "no track"
NO_SUCH_GENRE = "no such genre"


def album_name(name: str, credit: str, artist: str) -> str:
    return f"Синглы · {credit}" if name == SINGLES and credit != artist else name


def search_pattern(query: str) -> str:
    return f"%{query.casefold()}%"


def first_albums(tracks: Iterable[Mapping[str, Any]], covered: set[int], limit: int) -> list[int]:
    out: list[int] = []
    for track in tracks:
        album_id = track["album_id"]
        if album_id not in out and album_id in covered:
            out.append(album_id)
            if len(out) == limit:
                break
    return out


class CatalogQueries(Protocol):
    async def genres(self) -> list[Row]: ...

    async def artists(self, genre: str) -> list[Row]: ...

    async def artist_albums(self, name: str) -> list[Row]: ...

    async def albums(self, genre: str) -> list[Row]: ...

    async def album(self, album_id: int) -> Row | None: ...

    async def album_tracks(self, album_id: int) -> list[Row]: ...

    async def album_head(self, album_id: int) -> Row | None: ...

    async def search(self, pattern: str) -> Row: ...

    async def track(self, track_id: int) -> Row | None: ...

    async def genre_tracks(self, genre: str) -> list[Row]: ...

    async def track_rows(self, ids: Sequence[int]) -> list[Row]: ...

    async def duration(self, track_id: int) -> Row | None: ...

    async def library_tracks(self) -> list[Row]: ...


class LibraryState(Protocol):
    def fingerprint(self) -> str: ...

    def covered(self, album_ids: Iterable[int]) -> set[int]: ...
