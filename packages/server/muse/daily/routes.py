from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get
from litestar.params import FromPath

from muse.daily.domain import NO_PLAYLIST, DailyDay, DailyPage
from muse.daily.service import DailyPlaylists
from muse.identity.domain import User
from muse.shared.errors import domain_errors

ERRORS = {NO_PLAYLIST: 404}


@get("/daily")
@inject
async def daily(
    request: Request[User, str, Any], playlists: FromDishka[DailyPlaylists]
) -> DailyDay:
    return await playlists.latest(request.user.id)


@get("/daily/{pid:int}")
@inject
async def daily_playlist(pid: FromPath[int], playlists: FromDishka[DailyPlaylists]) -> DailyPage:
    return await playlists.require(pid)


router = Router(
    "/api", route_handlers=[daily, daily_playlist], exception_handlers=domain_errors(ERRORS)
)
