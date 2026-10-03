from collections.abc import Awaitable, Callable, Mapping

from muse.catalog.domain import Track
from muse.catalog.service import Catalog
from muse.daily.service import DailyPlaylists
from muse.discovery.service import Mixes
from muse.home.domain import (
    CONTINUE_LIMIT,
    FORGOTTEN_WINDOW_MS,
    HOME_TTL_S,
    MIX_WINDOW_MS,
    PARTNER_RECENT_LIMIT,
    RECENT_LIMIT,
    TOP_ARTISTS_WINDOW_MS,
    ContinueCard,
    HomeQueries,
    HomeView,
    MixCard,
    forgotten_albums,
    home_key,
    mix_genres,
)
from muse.identity.domain import Users
from muse.insights.service import ListeningStats
from muse.shared.cache import Cache
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.together.service import Ours

type Builder = Callable[[str, str, Mapping[str, int]], Awaitable[ContinueCard | None]]


class ContinueCards:
    def __init__(self, catalog: Catalog, mixes: Mixes, ours: Ours, daily: DailyPlaylists) -> None:
        self.catalog = catalog
        self.mixes = mixes
        self.ours = ours
        self.daily = daily
        self.builders: dict[str, Builder] = {
            "album": self._album,
            "playlist": self._playlist,
            "mix": self._mix,
            "genre": self._genre,
            "ours": self._ours,
            "daily": self._daily,
        }

    async def card(
        self, user_id: str, source: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        kind, _, argument = source.partition(":")
        builder = self.builders.get(kind)
        return await builder(user_id, argument, genres) if builder else None

    async def _album(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        head = await self.catalog.album_head(int(argument)) if argument.isdigit() else None
        if head is None:
            return None
        return {
            "kind": "album",
            "album_id": head["id"],
            "title": head["name"],
            "subtitle": head["artist"],
            "albums": [head["id"]],
        }

    async def _playlist(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        if not await self.catalog.has_playlist(argument):
            return None
        playlist = await self.catalog.playlist(argument)
        return {
            "kind": "playlist",
            "name": argument,
            "title": argument,
            "subtitle": "Плейлист",
            "albums": await self.catalog.cover_ids(playlist["tracks"]),
        }

    async def _mix(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        if argument not in genres:
            return None
        mix = await self.mixes.mix(user_id, argument)
        return {
            "kind": "mix",
            "genre": argument,
            "title": mix["title"],
            "subtitle": "Микс",
            "albums": await self.catalog.cover_ids(mix["tracks"]),
        }

    async def _genre(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        if argument not in genres:
            return None
        page = await self.catalog.genre(argument)
        return {
            "kind": "genre",
            "genre": argument,
            "title": argument,
            "subtitle": "Жанр",
            "albums": page["albums"],
        }

    async def _ours(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        ours = await self.ours.listing()
        if not ours["tracks"]:
            return None
        return {
            "kind": "ours",
            "title": "Наш плейлист",
            "subtitle": "На двоих",
            "albums": ours["albums"],
        }

    async def _daily(
        self, user_id: str, argument: str, genres: Mapping[str, int]
    ) -> ContinueCard | None:
        daily = await self.daily.playlist(int(argument)) if argument.isdigit() else None
        if daily is None:
            return None
        return {
            "kind": "daily",
            "id": daily["id"],
            "title": daily["title"],
            "subtitle": "Подборка дня",
            "albums": daily["albums"],
        }


class HomeFeed:
    def __init__(
        self,
        queries: HomeQueries,
        catalog: Catalog,
        cards: ContinueCards,
        mixes: Mixes,
        stats: ListeningStats,
        cache: Cache,
        users: Users,
        clock: Clock,
    ) -> None:
        self.queries = queries
        self.catalog = catalog
        self.cards = cards
        self.mixes = mixes
        self.stats = stats
        self.cache = cache
        self.users = users
        self.clock = clock

    async def home(self, user_id: str) -> HomeView:
        key = home_key(user_id, self.clock.today())
        return await self.cache.get_or_compute(key, HOME_TTL_S, lambda: self._compose(user_id))

    async def _compose(self, user_id: str) -> HomeView:
        partner_id = self.users.partner_id(user_id)
        genres = await self.catalog.genre_counts()
        now = self.clock.now_ms()
        heard = await self.queries.heard_albums(user_id, now - FORGOTTEN_WINDOW_MS)
        return {
            "continue": await self._continue(user_id, genres),
            "recent": await self._recent(user_id, RECENT_LIMIT),
            "top_artists": await self.stats.top_artists(user_id, now - TOP_ARTISTS_WINDOW_MS),
            "mixes": await self._mixes(user_id, genres, now),
            "forgotten": forgotten_albums(
                await self.catalog.albums(), heard, user_id, self.clock.today()
            ),
            "both_like": await self.catalog.tracks_in_order(
                await self.queries.both_liked(user_id, partner_id)
            ),
            "partner_recent": await self._recent(partner_id, PARTNER_RECENT_LIMIT),
        }

    async def _recent(self, user_id: str, limit: int) -> list[Track]:
        ids = await self.queries.recent_track_ids(user_id, limit)
        return await self.catalog.tracks_in_order(ids)

    async def _continue(self, user_id: str, genres: Mapping[str, int]) -> list[ContinueCard]:
        out: list[ContinueCard] = []
        for source in await self.queries.recent_sources(user_id):
            card = await self.cards.card(user_id, source, genres)
            if card:
                out.append(card)
            if len(out) == CONTINUE_LIMIT:
                break
        return out

    async def _mixes(self, user_id: str, genres: Mapping[str, int], now: int) -> list[MixCard]:
        ranked = await self.queries.genre_ranking(user_id, now - MIX_WINDOW_MS)
        cards: list[MixCard] = []
        for genre in mix_genres(ranked, list(genres)):
            mix = await self.mixes.mix(user_id, genre)
            cards.append(
                {
                    "genre": genre,
                    "title": mix["title"],
                    "tracks": len(mix["tracks"]),
                    "albums": await self.catalog.cover_ids(mix["tracks"]),
                }
            )
        return cards


class HomeRefresh:
    def __init__(self, cache: Cache, users: Users, clock: Clock, uow: UnitOfWork) -> None:
        self.cache = cache
        self.users = users
        self.clock = clock
        self.uow = uow

    async def drop(self, event: object) -> None:
        keys = [home_key(user.id, self.clock.today()) for user in self.users.all]

        async def forget() -> None:
            await self.cache.delete(*keys)

        self.uow.after_commit(forget)
