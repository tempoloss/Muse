import random
from collections.abc import Awaitable, Callable
from datetime import date
from functools import partial

import anyio

from muse.catalog.domain import NO_SUCH_GENRE, NO_TRACK, Track
from muse.catalog.service import Catalog
from muse.discovery.domain import (
    DAY_MS,
    MIX_PLAYED_DAYS,
    MIX_TTL_S,
    RADIO_RECENT_MS,
    GenreTracks,
    ListeningHistory,
    Mix,
    RadioModel,
    RadioTaste,
    build_radio_model,
    draw_mix,
    draw_radio,
    mix_key,
    mix_title,
)
from muse.identity.domain import Users
from muse.shared.cache import Cache
from muse.shared.clock import Clock
from muse.shared.errors import DomainError


class RadioModelCache:
    def __init__(self) -> None:
        self._lock = anyio.Lock()
        self._fingerprint: str | None = None
        self._model: RadioModel | None = None

    async def get(self, fingerprint: str, build: Callable[[], Awaitable[RadioModel]]) -> RadioModel:
        async with self._lock:
            if self._model is None or self._fingerprint != fingerprint:
                self._model = await build()
                self._fingerprint = fingerprint
            return self._model


class RadioModels:
    def __init__(self, catalog: Catalog, cache: RadioModelCache) -> None:
        self.catalog = catalog
        self.cache = cache

    async def current(self) -> RadioModel:
        return await self.cache.get(await self.catalog.fingerprint(), self._build)

    async def _build(self) -> RadioModel:
        tracks = await self.catalog.library_tracks()
        return build_radio_model(tracks, await self.catalog.playlist_artists())


class Radio:
    def __init__(
        self, models: RadioModels, history: ListeningHistory, users: Users, clock: Clock
    ) -> None:
        self.models = models
        self.history = history
        self.users = users
        self.clock = clock

    async def tracks(
        self, user_id: str, seed_id: int, exclude: set[int], count: int
    ) -> list[Track]:
        model = await self.models.current()
        seed = model.by_id.get(seed_id)
        if seed is None:
            raise DomainError(NO_TRACK)
        recent = await self.history.played_since(user_id, self.clock.now_ms() - RADIO_RECENT_MS)
        partner = self.users.partner_id(user_id)
        taste = RadioTaste(await self.history.liked(user_id), await self.history.liked(partner))
        skip = exclude | recent | {seed_id}
        return draw_radio(model, seed, skip, taste, count, random.Random())


class Mixes:
    def __init__(
        self,
        catalog: Catalog,
        genre_tracks: GenreTracks,
        history: ListeningHistory,
        cache: Cache,
        clock: Clock,
    ) -> None:
        self.catalog = catalog
        self.genre_tracks = genre_tracks
        self.history = history
        self.cache = cache
        self.clock = clock

    async def mix(self, user_id: str, genre: str) -> Mix:
        day = self.clock.today()
        compose = partial(self._compose, user_id, genre, day)
        return await self.cache.get_or_compute(mix_key(user_id, genre, day), MIX_TTL_S, compose)

    async def genre_mix(self, user_id: str, genre: str) -> Mix:
        if genre not in await self.catalog.genre_counts():
            raise DomainError(NO_SUCH_GENRE)
        return await self.mix(user_id, genre)

    async def _compose(self, user_id: str, genre: str, day: date) -> Mix:
        candidates = await self.genre_tracks.by_id(genre)
        liked = await self.history.liked(user_id)
        since = self.clock.now_ms() - MIX_PLAYED_DAYS * DAY_MS
        played = await self.history.counted_since(user_id, since)
        tracks = draw_mix(candidates, liked, played, random.Random(f"{user_id}:{genre}:{day}"))
        return {
            "genre": genre,
            "title": mix_title(genre),
            "tracks": tracks,
            "albums": await self.catalog.cover_ids(tracks),
        }
