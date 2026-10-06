from collections.abc import Sequence
from typing import cast

from muse.catalog.domain import (
    ALBUM_NAME,
    ARTIST,
    PLAYABLE,
    TRACK_COLUMNS,
    AlbumCard,
    AlbumHead,
    AlbumRecord,
    AlbumTrack,
    ArtistAlbum,
    ArtistCount,
    GenreCount,
    LibraryTrack,
    RunRow,
    SearchResult,
    StoredTrack,
    Track,
    TrackDuration,
    TrackPath,
)
from muse.shared.db import CatalogDb

GENRES = (
    f"SELECT al.genre, COUNT(DISTINCT {ARTIST}) artists, COUNT(*) tracks {PLAYABLE}"
    "GROUP BY al.genre ORDER BY tracks DESC"
)
ARTISTS = f"SELECT {ARTIST} name, COUNT(DISTINCT t.album_id) albums, COUNT(*) tracks {PLAYABLE}"
ARTIST_ALBUMS = (
    f"SELECT al.id, {ALBUM_NAME} name, al.year, al.genre, COUNT(*) ntracks {PLAYABLE}"
    f"AND {ARTIST}=? GROUP BY al.id ORDER BY al.year, al.name"
)
ALBUMS = (
    f"SELECT al.id, {ALBUM_NAME} name, al.year, al.genre, {ARTIST} artist, COUNT(*) ntracks "
    f"{PLAYABLE}"
)
ALBUM = (
    "SELECT al.*, COALESCE(ar.canonical, al.artist) who FROM albums al "
    "LEFT JOIN artists ar ON ar.name=al.artist WHERE al.id=?"
)
ALBUM_TRACKS = "SELECT id,num,title,dur FROM tracks WHERE album_id=? AND status='ok' ORDER BY num"
ALBUM_HEAD = (
    f"SELECT al.id, {ALBUM_NAME} name, {ARTIST} artist {PLAYABLE}AND al.id=? GROUP BY al.id"
)
SEARCH_ARTISTS = (
    f"SELECT {ARTIST} name, COUNT(DISTINCT t.album_id) albums, COUNT(*) tracks {PLAYABLE}"
    f"AND {ARTIST} IN (SELECT {ARTIST} {PLAYABLE}AND (uc(t.artist) LIKE ? OR uc(ar.canonical) LIKE ?)) "
    f"GROUP BY {ARTIST} ORDER BY tracks DESC LIMIT 20"
)
SEARCH_ALBUMS = (
    f"SELECT al.id, {ALBUM_NAME} name, al.year, al.genre, {ARTIST} artist {PLAYABLE}"
    f"AND uc({ALBUM_NAME}) LIKE ? GROUP BY al.id LIMIT 20"
)
SEARCH_TRACKS = (
    f"SELECT t.id, t.title, {ALBUM_NAME} album, t.album_id, {ARTIST} artist, t.dur {PLAYABLE}"
    "AND uc(t.title) LIKE ? LIMIT 20"
)
TRACK = (
    f"SELECT t.id, t.title, {ALBUM_NAME} album, {ARTIST} artist, t.dur, t.num, t.album_id "
    f"{PLAYABLE}AND t.id=?"
)
GENRE_TRACKS = (
    f"SELECT {TRACK_COLUMNS} {PLAYABLE}"
    f"AND al.genre=? ORDER BY {ARTIST} COLLATE NOCASE, al.name COLLATE NOCASE, t.num, t.id"
)
DURATION = "SELECT dur FROM tracks WHERE id=? AND status='ok'"
LIBRARY_TRACKS = f"SELECT {TRACK_COLUMNS}, al.genre {PLAYABLE}"


class SqlCatalog:
    def __init__(self, db: CatalogDb) -> None:
        self.db = db

    async def genres(self) -> list[GenreCount]:
        return cast("list[GenreCount]", await self.db.rows(GENRES))

    async def artists(self, genre: str) -> list[ArtistCount]:
        sql = (
            ARTISTS
            + ("AND al.genre=? " if genre else "")
            + f"GROUP BY {ARTIST} ORDER BY tracks DESC"
        )
        return cast("list[ArtistCount]", await self.db.rows(sql, (genre,) if genre else ()))

    async def artist_albums(self, name: str) -> list[ArtistAlbum]:
        return cast("list[ArtistAlbum]", await self.db.rows(ARTIST_ALBUMS, (name,)))

    async def albums(self, genre: str) -> list[AlbumCard]:
        sql = ALBUMS + ("AND al.genre=? " if genre else "")
        sql += f"GROUP BY al.id ORDER BY {ARTIST}, al.year, al.name"
        return cast("list[AlbumCard]", await self.db.rows(sql, (genre,) if genre else ()))

    async def album(self, album_id: int) -> AlbumRecord | None:
        return cast("AlbumRecord | None", await self.db.row(ALBUM, (album_id,)))

    async def album_tracks(self, album_id: int) -> list[AlbumTrack]:
        return cast("list[AlbumTrack]", await self.db.rows(ALBUM_TRACKS, (album_id,)))

    async def album_head(self, album_id: int) -> AlbumHead | None:
        return cast("AlbumHead | None", await self.db.row(ALBUM_HEAD, (album_id,)))

    async def search(self, pattern: str) -> SearchResult:
        return cast(
            "SearchResult",
            {
                "artists": await self.db.rows(SEARCH_ARTISTS, (pattern, pattern)),
                "albums": await self.db.rows(SEARCH_ALBUMS, (pattern,)),
                "tracks": await self.db.rows(SEARCH_TRACKS, (pattern,)),
            },
        )

    async def track(self, track_id: int) -> Track | None:
        return cast("Track | None", await self.db.row(TRACK, (track_id,)))

    async def genre_tracks(self, genre: str) -> list[Track]:
        return cast("list[Track]", await self.db.rows(GENRE_TRACKS, (genre,)))

    async def track_rows(self, ids: Sequence[int]) -> list[Track]:
        marks = ",".join("?" * len(ids))
        sql = f"SELECT {TRACK_COLUMNS} {PLAYABLE}AND t.id IN ({marks})"
        return cast("list[Track]", await self.db.rows(sql, ids))

    async def duration(self, track_id: int) -> TrackDuration | None:
        return cast("TrackDuration | None", await self.db.row(DURATION, (track_id,)))

    async def library_tracks(self) -> list[LibraryTrack]:
        return cast("list[LibraryTrack]", await self.db.rows(LIBRARY_TRACKS))

    async def playable_paths(self) -> list[StoredTrack]:
        sql = f"SELECT {TRACK_COLUMNS}, t.path {PLAYABLE}"
        return cast("list[StoredTrack]", await self.db.rows(sql))

    async def track_path(self, track_id: int) -> TrackPath | None:
        sql = "SELECT path FROM tracks WHERE id=? AND status='ok'"
        return cast("TrackPath | None", await self.db.row(sql, (track_id,)))

    async def run_rows(self, ids: Sequence[int]) -> list[RunRow]:
        marks = ",".join("?" * len(ids))
        sql = f"SELECT id, path, dur FROM tracks WHERE status='ok' AND id IN ({marks})"
        return cast("list[RunRow]", await self.db.rows(sql, ids))
