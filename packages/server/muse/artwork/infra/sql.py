from muse.artwork.domain import AlbumRecord, AlbumTrack
from muse.shared.db import CatalogDb

ALBUM = "SELECT name, artist, canonical FROM albums WHERE id=?"
ALBUM_TRACKS = "SELECT path, title FROM tracks WHERE album_id=? AND status='ok' ORDER BY num"


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
