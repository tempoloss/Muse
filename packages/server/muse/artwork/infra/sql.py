from muse.artwork.domain import AlbumRecord, AlbumTrack
from muse.catalog.domain import ARTIST, PLAYABLE
from muse.shared.db import CatalogDb

ALBUM = "SELECT name, artist, canonical FROM albums WHERE id=?"
ALBUM_TRACKS = "SELECT path, title FROM tracks WHERE album_id=? AND status='ok' ORDER BY num"
ARTIST_ALBUMS = (
    f"SELECT al.id, COUNT(*) n {PLAYABLE}AND {ARTIST}=? GROUP BY al.id ORDER BY n DESC, al.id"
)
ALBUM_IDS = "SELECT DISTINCT album_id FROM tracks WHERE status='ok' ORDER BY album_id"


class SqlArtworkLibrary:
    def __init__(self, db: CatalogDb) -> None:
        self.db = db

    async def album(self, album_id: int) -> AlbumRecord | None:
        row = await self.db.row(ALBUM, (album_id,))
        if row is None:
            return None
        tracks = await self.db.rows(ALBUM_TRACKS, (album_id,))
        return AlbumRecord(
            row["name"],
            row["artist"],
            row["canonical"],
            tuple(AlbumTrack(track["path"], track["title"]) for track in tracks),
        )

    async def artist_album_ids(self, name: str) -> list[int]:
        return [row["id"] for row in await self.db.rows(ARTIST_ALBUMS, (name,))]

    async def album_ids(self) -> list[int]:
        return [row["album_id"] for row in await self.db.rows(ALBUM_IDS)]
