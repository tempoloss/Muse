from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

import httpx

from muse.artwork.domain import (
    CREDIT_SPLIT,
    Ask,
    Candidate,
    Sleep,
    TransientError,
    album_asks,
    credit,
    credited_hit,
    norm,
    same_title,
    same_tracks,
    tracklist_suspects,
)
from muse.catalog.domain import SINGLES

DEEZER = "https://api.deezer.com"
ITUNES_SEARCH = "https://itunes.apple.com/search"
DEEZER_PAUSE_S = 0.2
ITUNES_PAUSE_S = 3.0
DOWNLOAD_TIMEOUT_S = 15
DEEZER_ALBUMS_PAGE = 500
DEEZER_TRACKLIST_LIMIT = 200
ITUNES_LIMIT = 25
SHORT_NAME_CHARS = 4
TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL)

type Json = dict[str, Any]
type Search = Callable[[str, str], Awaitable[list[Candidate]]]
type Discography = Callable[[Sequence[str | None], str | None], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class Store:
    search: Search
    lists_tracks: bool
    discography: Discography | None = None


def best_artist(found: Sequence[Json], name: str) -> Json | None:
    who, wanted = credit(name), name.casefold()

    def named(item: Json) -> bool:
        return (item.get("name") or "").casefold() == wanted

    def rank(item: Json) -> tuple[bool, int]:
        return named(item), item.get("nb_fan") or 0

    matches = (
        item
        for item in found
        if who & credit(item.get("name")) and (len(norm(name)) >= SHORT_NAME_CHARS or named(item))
    )
    return max(matches, key=rank, default=None)


def discography_art(found: Sequence[Json], album: str | None) -> str | None:
    want = norm(album)
    for matches in (lambda title: title == want, lambda title: same_title(want, title)):
        for item in found:
            art = item.get("cover_xl") or ""
            if art and "/cover//" not in art and matches(norm(item.get("title"))):
                return art
    return None


def quota_checked(found: Json) -> Json:
    if "error" in found:
        raise TransientError(found["error"])
    return found


class OnlineStores:
    def __init__(self, client: httpx.AsyncClient, sleep: Sleep) -> None:
        self.client = client
        self.sleep = sleep
        self.stores = (
            Store(self.deezer_search, True, self.deezer_artist_album),
            Store(partial(self.itunes_search, "US"), False),
            Store(partial(self.itunes_search, "RU"), False),
        )

    async def get_json(self, url: str, params: Mapping[str, str | int] | None) -> Any:
        try:
            response = await self.client.get(url, params=params, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except (*TRANSPORT_ERRORS, ValueError) as error:
            raise TransientError(error) from error

    async def download(self, url: str) -> bytes:
        try:
            response = await self.client.get(url, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True)
            response.raise_for_status()
        except TRANSPORT_ERRORS as error:
            raise TransientError(error) from error
        return response.content

    async def deezer_artist(self, name: str) -> Json | None:
        await self.sleep(DEEZER_PAUSE_S)
        query = {"q": CREDIT_SPLIT.split(name)[0]}
        found = quota_checked(await self.get_json(f"{DEEZER}/search/artist", query))
        return best_artist(found.get("data", []), name)

    async def artist_picture(self, name: str) -> str | None:
        artist = await self.deezer_artist(name)
        url = (artist or {}).get("picture_xl") or ""
        return url if url and "/artist//" not in url else None

    async def deezer_artist_album(
        self, names: Sequence[str | None], album: str | None
    ) -> str | None:
        artist = None
        for name in names:
            if name and (artist := await self.deezer_artist(name)):
                break
        if not artist:
            return None
        url: str | None = f"{DEEZER}/artist/{artist['id']}/albums"
        params: Mapping[str, int] | None = {"limit": DEEZER_ALBUMS_PAGE}
        found: list[Json] = []
        while url:
            await self.sleep(DEEZER_PAUSE_S)
            page = quota_checked(await self.get_json(url, params))
            found.extend(page.get("data", []))
            url, params = page.get("next"), None
        return discography_art(found, album)

    async def deezer_tracklist(self, album_id: object) -> list[str | None]:
        found = await self.get_json(
            f"{DEEZER}/album/{album_id}/tracks", {"limit": DEEZER_TRACKLIST_LIMIT}
        )
        return [track.get("title") for track in found.get("data", [])]

    def deezer_candidate(self, item: Json, kind: str) -> Candidate:
        album = item if kind == "album" else item.get("album", {})
        art = album.get("cover_xl") or ""
        tracklist = partial(self.deezer_tracklist, item.get("id")) if kind == "album" else None
        return Candidate(
            item.get("artist", {}).get("name"),
            album.get("title"),
            None if kind == "album" else item.get("title"),
            art if "/cover//" not in art else "",
            tracklist,
        )

    async def deezer_search(self, term: str, kind: str) -> list[Candidate]:
        await self.sleep(DEEZER_PAUSE_S)
        endpoint = "album" if kind == "album" else "track"
        found = quota_checked(await self.get_json(f"{DEEZER}/search/{endpoint}", {"q": term}))
        return [self.deezer_candidate(item, kind) for item in found.get("data", [])]

    async def itunes_search(self, country: str, term: str, kind: str) -> list[Candidate]:
        await self.sleep(ITUNES_PAUSE_S)
        query = {
            "term": term,
            "entity": "album" if kind == "album" else "song",
            "limit": ITUNES_LIMIT,
            "country": country,
        }
        found = await self.get_json(ITUNES_SEARCH, query)
        return [
            Candidate(
                item.get("artistName"),
                item.get("collectionName"),
                item.get("trackName"),
                (item.get("artworkUrl100") or "").replace("100x100bb", "600x600bb"),
            )
            for item in found.get("results", [])
        ]

    async def proven(
        self, candidates: Sequence[Candidate], want: str, titles: Sequence[str | None]
    ) -> Candidate | None:
        for candidate in tracklist_suspects(candidates, want):
            if candidate.tracklist and same_tracks(titles, await candidate.tracklist()):
                return candidate
        return None

    async def ask(
        self, store: Store, asks: Sequence[Ask], who: set[str], titles: Sequence[str | None]
    ) -> str | None:
        for ask in asks:
            if not ask.want or (ask.bare and not store.lists_tracks):
                continue
            candidates = [c for c in await store.search(ask.term, ask.kind) if c.art]
            hit = credited_hit(candidates, who, ask)
            if not hit and ask.kind == "album":
                hit = await self.proven(candidates, ask.want, titles)
            if hit:
                return hit.art
        return None

    async def album_art(
        self, names: Sequence[str | None], album: str | None, titles: Sequence[str | None]
    ) -> str | None:
        who: set[str] = set().union(*(credit(name) for name in names if name))
        asks = album_asks(names, album, titles)
        failed: TransientError | None = None
        for store in self.stores:
            try:
                if art := await self.ask(store, asks, who, titles):
                    return art
                if (
                    store.discography
                    and album != SINGLES
                    and (art := await store.discography(names, album))
                ):
                    return art
            except TransientError as error:
                failed = error
        if failed:
            raise failed
        return None
