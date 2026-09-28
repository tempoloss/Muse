from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from muse.artwork.domain import (
    FIRST_RETRY_S,
    LAST_RETRY_S,
    NO_ARTIST_IMAGE,
    NO_COVER,
    AlbumRecord,
    ArtworkFiles,
    ArtworkLibrary,
    ArtworkStores,
    ImageShelf,
    Sleep,
    TransientError,
    artist_key,
)
from muse.catalog.service import Catalog
from muse.shared.errors import DomainError

COVER_FAILURES = "covers: {count} albums hit store errors (last: {error}); retry in {wait}s"
ARTIST_FAILURES = "artists: {count} hit store errors (last: {error}); retry in {wait}s"

log = structlog.get_logger()


async def known(shelf: ImageShelf, key: str) -> bool:
    return await shelf.image(key) is not None or await shelf.known_missing(key)


class Artwork:
    def __init__(
        self,
        catalog: Catalog,
        library: ArtworkLibrary,
        files: ArtworkFiles,
        stores: ArtworkStores,
        sleep: Sleep,
    ) -> None:
        self.catalog = catalog
        self.library = library
        self.files = files
        self.stores = stores
        self.sleep = sleep

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

    async def cover_file(self, album_id: int, *, online: bool = False) -> Path | None:
        key = str(album_id)
        if found := await self.files.covers.image(key):
            return found
        if await self.files.covers.known_missing(key):
            return None
        album = await self.library.album(album_id)
        if album is None:
            return None
        data = await self.embedded_cover(album)
        if not data and online:
            titles = [track.title for track in album.tracks]
            url = await self.stores.album_art((album.canonical, album.artist), album.name, titles)
            if not url:
                await self.files.covers.mark_missing(key)
                return None
            data = await self.stores.download(url)
        if not data:
            return None
        return await self.files.covers.keep(key, data)

    async def embedded_cover(self, album: AlbumRecord) -> bytes | None:
        for track in album.tracks:
            audio = await self.catalog.track_file(track.path)
            if audio and (data := await self.files.embedded_picture(audio)):
                return data
        return None

    async def find_artist_image(self, name: str) -> str | None:
        key = artist_key(name)
        if await known(self.files.artists, key):
            return None
        picture, failed = await self.store_picture(name)
        source = "deezer"
        if not picture:
            picture, source = await self.top_album_cover(name), "cover"
        if not picture:
            if failed:
                raise failed
            await self.files.artists.mark_missing(key)
            return "none"
        await self.files.artists.keep(key, picture)
        return source

    async def store_picture(self, name: str) -> tuple[bytes | None, TransientError | None]:
        try:
            url = await self.stores.artist_picture(name)
            return (await self.stores.download(url) if url else None), None
        except TransientError as error:
            return None, error

    async def top_album_cover(self, name: str) -> bytes | None:
        for album_id in await self.library.artist_album_ids(name):
            data = await self.files.covers.load(str(album_id))
            if data is not None:
                return data
        return None

    async def warm(self) -> None:
        await self.warm_covers()
        await self.warm_artists()

    async def warm_covers(self) -> None:
        album_ids = await self.library.album_ids()
        todo = [aid for aid in album_ids if not await known(self.files.covers, str(aid))]
        found = await self.settle(todo, self.find_cover, COVER_FAILURES)
        log.info(f"covers: warmed {sum(path is not None for path in found)}/{len(todo)}")

    async def find_cover(self, album_id: int) -> Path | None:
        return await self.cover_file(album_id, online=True)

    async def warm_artists(self) -> None:
        names = [artist["name"] for artist in await self.catalog.artists()]
        todo = [name for name in names if not await known(self.files.artists, artist_key(name))]
        sources = Counter(await self.settle(todo, self.find_artist_image, ARTIST_FAILURES))
        log.info(
            f"artists: warmed {sources['deezer']} deezer, {sources['cover']} cover, "
            f"{sources['none']} none / {len(todo)}"
        )

    async def settle[T, R](
        self, todo: list[T], attempt: Callable[[T], Awaitable[R]], failure: str
    ) -> list[R]:
        done: list[R] = []
        wait = FIRST_RETRY_S
        while todo:
            failed: list[T] = []
            last: TransientError | None = None
            for item in todo:
                try:
                    done.append(await attempt(item))
                except TransientError as error:
                    failed.append(item)
                    last = error
            if failed:
                log.warning(failure.format(count=len(failed), error=last, wait=wait))
                await self.sleep(wait)
                wait = min(wait * 2, LAST_RETRY_S)
            todo = failed
        return done
