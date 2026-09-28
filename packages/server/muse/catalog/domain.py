import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
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
TRACK_FIELDS = ("id", "num", "title", "dur", "album_id", "album", "artist")
CATALOG_TTL_S = 86400
SEARCH_MIN_CHARS = 2
COVER_MOSAIC = 4
NO_SUCH_ARTIST = "no such artist"
NO_ALBUM = "no album"
NO_TRACK = "no track"
NO_SUCH_GENRE = "no such genre"
NO_PLAYLIST = "no playlist"
DEVICE_PREFIX = re.compile(r"^.*?/Music/")
DRIVE = re.compile(r"^[A-Za-z]:/")


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


@dataclass(frozen=True, slots=True)
class LibraryRoot:
    prefix: str

    @classmethod
    def at(cls, library_dir: PurePath) -> LibraryRoot:
        return cls(library_dir.as_posix().rstrip("/") + "/")

    def relative(self, stored: str | None) -> str | None:
        if not stored:
            return None
        path = stored.replace("\\", "/")
        if ".." in path.split("/"):
            return None
        if path.startswith("/") or DRIVE.match(path):
            if path[: len(self.prefix)].casefold() != self.prefix.casefold():
                return None
            path = path[len(self.prefix) :]
        return path or None

    def key(self, stored: str | None) -> str | None:
        relative = self.relative(stored)
        return relative.casefold() if relative else None


def playlist_key(line: str) -> str | None:
    entry = line.strip()
    if not entry or entry.startswith("#"):
        return None
    return DEVICE_PREFIX.sub("", entry.replace("\\", "/")).casefold()


def playlist_tracks(lines: Iterable[str], by_key: Mapping[str, Row]) -> list[Row]:
    out = []
    for line in lines:
        key = playlist_key(line)
        if key is not None and (row := by_key.get(key)):
            out.append({field: row[field] for field in TRACK_FIELDS})
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

    async def playable_paths(self) -> list[Row]: ...


class LibraryState(Protocol):
    def fingerprint(self) -> str: ...

    def covered(self, album_ids: Iterable[int]) -> set[int]: ...


class PlaylistSource(Protocol):
    def names(self) -> list[str]: ...

    def lines(self, name: str) -> list[str] | None: ...
