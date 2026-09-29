from typing import Annotated, Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, delete, get, post
from litestar.params import FromQuery, QueryParameter

from muse.catalog.domain import NO_TRACK
from muse.identity.domain import User
from muse.shared.errors import domain_errors
from muse.together.domain import FOLLOW_WAIT_S, PARTNER_FOLLOWS
from muse.together.schemas import LiveBody
from muse.together.service import Following, Live

ERRORS = {NO_TRACK: 404, PARTNER_FOLLOWS: 409}


@post("/live", status_code=200)
@inject
async def report_beat(
    data: LiveBody, request: Request[User, str, Any], live: FromDishka[Live]
) -> dict[str, Any]:
    return await live.beat(request.user.id, data.track_id, data.position, data.playing)


@get("/live")
@inject
async def live_view(request: Request[User, str, Any], live: FromDishka[Live]) -> dict[str, Any]:
    return await live.view(request.user.id)


@get("/live/follow")
@inject
async def follow(
    request: Request[User, str, Any],
    following: FromDishka[Following],
    since: FromQuery[int] = 0,
    wait: Annotated[float, QueryParameter(ge=0, le=FOLLOW_WAIT_S)] = FOLLOW_WAIT_S,
) -> dict[str, Any]:
    return await following.follow(request.user.id, since, wait)


@delete("/live/follow", status_code=204)
@inject
async def unfollow(request: Request[User, str, Any], following: FromDishka[Following]) -> None:
    following.unfollow(request.user.id)


router = Router(
    "/api",
    route_handlers=[report_beat, live_view, follow, unfollow],
    exception_handlers=domain_errors(ERRORS),
)
