from muse.catalog.domain import Track
from muse.catalog.service import Catalog
from muse.lyrics.domain import LYRICS_TTL_S, LyricsSource, LyricsView, album_param
from muse.shared.cache import Cache


class Lyrics:
    def __init__(self, catalog: Catalog, source: LyricsSource, cache: Cache) -> None:
        self.catalog = catalog
        self.source = source
        self.cache = cache

    async def for_track(self, track_id: int) -> LyricsView:
        track = await self.catalog.track(track_id)
        return await self.cache.get_or_compute(
            f"lyrics:{track_id}", LYRICS_TTL_S, lambda: self.find(track)
        )

    async def find(self, track: Track) -> LyricsView:
        durs = track["dur"]
        return await self.source.find(
            artist=track["artist"],
            title=track["title"],
            album=album_param(track["album"]),
            duration=None if durs is None else float(durs),
        )
