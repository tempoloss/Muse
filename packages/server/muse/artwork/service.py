from pathlib import Path

from muse.artwork.domain import (
    NO_ARTIST_IMAGE,
    NO_COVER,
    AlbumRecord,
    ArtworkFiles,
    ArtworkLibrary,
    artist_key,
)
from muse.catalog.service import Catalog
from muse.shared.errors import DomainError


class Artwork:
    def __init__(self, catalog: Catalog, library: ArtworkLibrary, files: ArtworkFiles) -> None:
        self.catalog = catalog
        self.library = library
        self.files = files

    async def cover(self, album_id: int, size: int) -> Path:
        found = await self.cover_file(album_id)
        if found is None:
            raise DomainError(NO_COVER)
        return await self.files.covers.thumbnail(found, size)

    async def artist_image(self, name: str, size: int) -> Path:
        found = await self.files.artists.image(artist_key(name))
        if found is None:
            raise DomainError(NO_ARTIST_IMAGE)
        return await self.files.artists.thumbnail(found, size)

    async def cover_file(self, album_id: int) -> Path | None:
        key = str(album_id)
        if found := await self.files.covers.image(key):
            return found
        if await self.files.covers.known_missing(key):
            return None
        album = await self.library.album(album_id)
        if album is None:
            return None
        data = await self.embedded_cover(album)
        if not data:
            return None
        return await self.files.covers.keep(key, data)

    async def embedded_cover(self, album: AlbumRecord) -> bytes | None:
        for track in album.tracks:
            audio = await self.catalog.track_file(track.path)
            if audio and (data := await self.files.embedded_picture(audio)):
                return data
        return None
