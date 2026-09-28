import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from muse.catalog.domain import SINGLES

NO_COVER = "no cover"
NO_ARTIST_IMAGE = "no artist image"
THUMB_SIZES = (128, 384)
FIRST_RETRY_S = 60
LAST_RETRY_S = 1800
SINGLES_ASKS = 3
TRACKLIST_PROOFS = 5
EXTENSION_MIN_CHARS = 4
SHARED_TRACKS_MIN = 3
SHARED_TRACKS_SHARE = 0.6

CREDIT_SPLIT = re.compile(r"\s*(?:,|&|\s+x\s+|\bfeat\.?\s|\bft\.?\s)\s*", re.IGNORECASE)
BRACKETED = re.compile(r"\s*[(\[][^)\]]*[)\]]")
RELEASE_SUFFIX = re.compile(r"\s+-\s+(single|ep)\s*$", re.IGNORECASE)
NON_WORD = re.compile(r"[\W_]+")

type Sleep = Callable[[float], Awaitable[None]]
type Tracklist = Callable[[], Awaitable[list[str | None]]]


class TransientError(Exception):
    pass


def norm(value: str | None) -> str:
    text = value or ""
    bare = RELEASE_SUFFIX.sub("", BRACKETED.sub("", text))
    return (NON_WORD.sub("", bare.casefold()) or text.casefold().strip()).replace("ё", "е")


def credit(value: str | None) -> set[str]:
    text = value or ""
    return {name for name in map(norm, [*CREDIT_SPLIT.split(text), text]) if name}


def same_title(a: str, b: str) -> bool:
    short, long_ = sorted((a, b), key=len)
    return bool(short) and (
        short == long_ or (len(short) >= EXTENSION_MIN_CHARS and long_.startswith(short))
    )


def same_tracks(ours: Sequence[str | None], theirs: Sequence[str | None]) -> bool:
    mine = {norm(title) for title in ours} - {""}
    shared = len(mine & {norm(title) for title in theirs})
    return shared >= SHARED_TRACKS_MIN and shared >= SHARED_TRACKS_SHARE * len(mine)


def artist_key(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class Candidate:
    artist: str | None
    album: str | None
    track: str | None
    art: str
    tracklist: Tracklist | None = None


@dataclass(frozen=True, slots=True)
class Ask:
    term: str
    kind: str
    by_track: bool
    want: str
    bare: bool

    def title(self, candidate: Candidate) -> str:
        return norm(candidate.track if self.by_track else candidate.album)


def album_asks(
    names: Sequence[str | None], album: str | None, titles: Sequence[str | None]
) -> list[Ask]:
    artist = next(name for name in names if name)
    if album == SINGLES:
        return [
            Ask(f"{artist} {title}", "song", True, norm(title), False)
            for title in titles[:SINGLES_ASKS]
        ]
    asks = [Ask(f"{artist} {album}", kind, False, norm(album), False) for kind in ("album", "song")]
    asks.append(Ask(album or "", "album", False, norm(album), True))
    return asks


def credited_hit(candidates: Sequence[Candidate], who: set[str], ask: Ask) -> Candidate | None:
    mine = [candidate for candidate in candidates if who & credit(candidate.artist)]
    return next((c for c in mine if ask.title(c) == ask.want), None) or next(
        (c for c in mine if same_title(ask.want, ask.title(c))), None
    )


def tracklist_suspects(candidates: Sequence[Candidate], want: str) -> list[Candidate]:
    suspects = [c for c in candidates if c.tracklist and norm(c.album) == want]
    return suspects[:TRACKLIST_PROOFS]


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

    async def artist_album_ids(self, name: str) -> list[int]: ...

    async def album_ids(self) -> list[int]: ...


class ArtworkStores(Protocol):
    async def album_art(
        self, names: Sequence[str | None], album: str | None, titles: Sequence[str | None]
    ) -> str | None: ...

    async def artist_picture(self, name: str) -> str | None: ...

    async def download(self, url: str) -> bytes: ...


class ImageShelf(Protocol):
    async def image(self, key: str) -> Path | None: ...

    async def load(self, key: str) -> bytes | None: ...

    async def known_missing(self, key: str) -> bool: ...

    async def mark_missing(self, key: str) -> None: ...

    async def keep(self, key: str, data: bytes) -> Path: ...

    async def thumbnail(self, image: Path, size: int) -> Path: ...


class ArtworkFiles(Protocol):
    @property
    def covers(self) -> ImageShelf: ...

    @property
    def artists(self) -> ImageShelf: ...

    async def embedded_picture(self, audio: Path) -> bytes | None: ...
