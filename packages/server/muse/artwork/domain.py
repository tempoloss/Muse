import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

NO_COVER = "no cover"
NO_ARTIST_IMAGE = "no artist image"
THUMB_SIZES = (128, 384)


def artist_key(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class AlbumTrack:
    path: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class AlbumRecord:
    name: str | None
    artist: str | None
    canonical: str | None
    tracks: tuple[AlbumTrack, ...]


class ArtworkLibrary(Protocol):
    async def album(self, album_id: int) -> AlbumRecord | None: ...


class ImageShelf(Protocol):
    async def image(self, key: str) -> Path | None: ...

    async def known_missing(self, key: str) -> bool: ...

    async def keep(self, key: str, data: bytes) -> Path: ...

    async def thumbnail(self, image: Path, size: int) -> Path: ...


class ArtworkFiles(Protocol):
    @property
    def covers(self) -> ImageShelf: ...

    @property
    def artists(self) -> ImageShelf: ...

    async def embedded_picture(self, audio: Path) -> bytes | None: ...
