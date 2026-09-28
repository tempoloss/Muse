import threading
from pathlib import Path

import anyio
import mutagen
import structlog
from PIL import Image

from muse.artwork.domain import THUMB_SIZES

THUMB_QUALITY = 82

log = structlog.get_logger()


def write_atomically(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.stem}.{threading.get_ident()}.tmp")
    temporary.write_bytes(data)
    try:
        temporary.replace(target)
    except PermissionError:
        temporary.unlink(missing_ok=True)
    return target


def make_thumbnail(source: Path, target: Path, size: int) -> Path:
    if target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{threading.get_ident()}.tmp")
        with Image.open(source) as image:
            small = image.convert("RGB")
            small.thumbnail((size, size), Image.Resampling.LANCZOS)
            small.save(temporary, "JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)
        temporary.replace(target)
    except Exception as error:
        log.warning(f"thumbs: {source.name}: {error}")
        return source
    return target


def read_embedded_picture(audio: Path) -> bytes | None:
    try:
        parsed = mutagen.File(str(audio))
        for frame in parsed.tags.getall("APIC") if parsed and parsed.tags else []:
            if getattr(frame, "data", None):
                return frame.data
    except Exception:
        return None
    return None


class LocalShelf:
    def __init__(self, directory: Path, thumbs: Path) -> None:
        self.directory = directory
        self.thumbs = thumbs

    def _image(self, key: str) -> Path:
        return self.directory / f"{key}.jpg"

    def _miss(self, key: str) -> Path:
        return self.directory / f"{key}.none"

    async def image(self, key: str) -> Path | None:
        path = self._image(key)
        return path if await anyio.Path(path).is_file() else None

    async def load(self, key: str) -> bytes | None:
        path = anyio.Path(self._image(key))
        return await path.read_bytes() if await path.is_file() else None

    async def known_missing(self, key: str) -> bool:
        return await anyio.Path(self._miss(key)).is_file()

    async def mark_missing(self, key: str) -> None:
        await anyio.Path(self.directory).mkdir(parents=True, exist_ok=True)
        await anyio.Path(self._miss(key)).touch()

    async def keep(self, key: str, data: bytes) -> Path:
        return await anyio.to_thread.run_sync(write_atomically, self._image(key), data)

    async def thumbnail(self, image: Path, size: int) -> Path:
        if size not in THUMB_SIZES:
            return image
        target = self.thumbs / str(size) / image.name
        return await anyio.to_thread.run_sync(make_thumbnail, image, target, size)


class LocalArtworkFiles:
    def __init__(self, covers_dir: Path, artists_dir: Path, thumbs_dir: Path) -> None:
        self.covers = LocalShelf(covers_dir, thumbs_dir / "covers")
        self.artists = LocalShelf(artists_dir, thumbs_dir / "artists")

    async def embedded_picture(self, audio: Path) -> bytes | None:
        return await anyio.to_thread.run_sync(read_embedded_picture, audio)
