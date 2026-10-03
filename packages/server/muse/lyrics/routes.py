from dishka.integrations.litestar import FromDishka, inject
from litestar import Router, get
from litestar.params import FromPath

from muse.catalog.domain import NO_TRACK
from muse.lyrics.domain import LYRICS_UNAVAILABLE, LyricsView
from muse.lyrics.service import Lyrics
from muse.shared.errors import domain_errors

ERRORS = {NO_TRACK: 404, LYRICS_UNAVAILABLE: 503}


@get("/lyrics/{tid:int}")
@inject
async def lyrics(tid: FromPath[int], finder: FromDishka[Lyrics]) -> LyricsView:
    return await finder.for_track(tid)


router = Router("/api", route_handlers=[lyrics], exception_handlers=domain_errors(ERRORS))
