import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol, TypedDict

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
NO_PLAYLIST = "no playlist"
FILE_GONE = "file gone"
BAD_RUN = "bad run"
RUN_SONGS = 100
RUN_CHUNK = 64 * 1024
RUN_IDS = re.compile(r"\d{1,9}(?:,\d{1,9})*")
DEVICE_PREFIX = re.compile(r"^.*?/Music/")
DRIVE = re.compile(r"^[A-Za-z]:/")


def album_name(name: str, credit: str, artist: str) -> str:
    return f"Синглы · {credit}" if name == SINGLES and credit != artist else name


def search_pattern(query: str) -> str:
    return f"%{query.casefold()}%"


class GenreCount(TypedDict):
    genre: str | None
    artists: int
    tracks: int


class ArtistCount(TypedDict):
    name: str
    albums: int
    tracks: int


class ArtistAlbum(TypedDict):
    id: int
    name: str
    year: str | None
    genre: str | None
    ntracks: int


class AlbumMatch(TypedDict):
    id: int
    name: str
    year: str | None
    genre: str | None
    artist: str


class AlbumCard(AlbumMatch):
    ntracks: int


class AlbumRecord(TypedDict):
    id: int
    name: str
    artist: str
    who: str
    year: str | None
    genre: str | None


class AlbumHead(TypedDict):
    id: int
    name: str
    artist: str


class AlbumTrack(TypedDict):
    id: int
    num: int | None
    title: str
    dur: int | None


class TrackMatch(TypedDict):
    id: int
    title: str
    album: str
    album_id: int
    artist: str
    dur: int | None


class Track(TrackMatch):
    num: int | None


class LibraryTrack(Track):
    genre: str | None


class StoredTrack(Track):
    path: str | None


class TrackPath(TypedDict):
    path: str | None


class RunRow(TypedDict):
    id: int
    path: str | None
    dur: int | None


class TrackDuration(TypedDict):
    dur: int | None


class SearchResult(TypedDict):
    artists: list[ArtistCount]
    albums: list[AlbumMatch]
    tracks: list[TrackMatch]


class ArtistPage(TypedDict):
    name: str
    genre: str | None
    albums: list[ArtistAlbum]


class AlbumPage(TypedDict):
    id: int
    name: str
    year: str | None
    genre: str | None
    artist: str
    cover: str
    tracks: list[AlbumTrack]


class GenrePage(TypedDict):
    genre: str
    title: str
    tracks: list[Track]
    albums: list[int]


class PlaylistCard(TypedDict):
    name: str
    tracks: int
    dur: int
    albums: list[int]


class PlaylistPage(TypedDict):
    name: str
    tracks: list[Track]
    albums: list[int]


def track_of(row: Track) -> Track:
    return {
        "id": row["id"],
        "num": row["num"],
        "title": row["title"],
        "dur": row["dur"],
        "album_id": row["album_id"],
        "album": row["album"],
        "artist": row["artist"],
    }


def first_albums(tracks: Iterable[TrackMatch], covered: set[int], limit: int) -> list[int]:
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


def playlist_tracks(lines: Iterable[str], by_key: Mapping[str, StoredTrack]) -> list[Track]:
    out: list[Track] = []
    for line in lines:
        key = playlist_key(line)
        if key is not None and (row := by_key.get(key)):
            out.append(track_of(row))
    return out


class CatalogQueries(Protocol):
    async def genres(self) -> list[GenreCount]: ...

    async def artists(self, genre: str) -> list[ArtistCount]: ...

    async def artist_albums(self, name: str) -> list[ArtistAlbum]: ...

    async def albums(self, genre: str) -> list[AlbumCard]: ...

    async def album(self, album_id: int) -> AlbumRecord | None: ...

    async def album_tracks(self, album_id: int) -> list[AlbumTrack]: ...

    async def album_head(self, album_id: int) -> AlbumHead | None: ...

    async def search(self, pattern: str) -> SearchResult: ...

    async def track(self, track_id: int) -> Track | None: ...

    async def genre_tracks(self, genre: str) -> list[Track]: ...

    async def track_rows(self, ids: Sequence[int]) -> list[Track]: ...

    async def duration(self, track_id: int) -> TrackDuration | None: ...

    async def library_tracks(self) -> list[LibraryTrack]: ...

    async def playable_paths(self) -> list[StoredTrack]: ...

    async def track_path(self, track_id: int) -> TrackPath | None: ...

    async def run_rows(self, ids: Sequence[int]) -> list[RunRow]: ...


class LibraryState(Protocol):
    def fingerprint(self) -> str: ...

    def covered(self, album_ids: Iterable[int]) -> set[int]: ...


class PlaylistSource(Protocol):
    def names(self) -> list[str]: ...

    def lines(self, name: str) -> list[str] | None: ...


class TrackStorage(Protocol):
    def locate(self, stored: str | None) -> Path | None: ...

    def stream_bytes(self, stored: str | None) -> bytes | None: ...
