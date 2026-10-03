from typing import Annotated, Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get
from litestar.params import FromQuery, QueryParameter

from muse.identity.domain import User
from muse.insights.domain import BAD_WHO, StatsSummary, UsStats
from muse.insights.service import ListeningStats
from muse.shared.errors import domain_errors

ERRORS = {BAD_WHO: 422}


@get("/stats")
@inject
async def stats(
    request: Request[User, str, Any],
    listening: FromDishka[ListeningStats],
    days: Annotated[int, QueryParameter(ge=1, le=365)] = 30,
    who: FromQuery[str] = "me",
) -> StatsSummary:
    return await listening.summary(request.user.id, days, who)


@get("/stats/us")
@inject
async def stats_us(
    request: Request[User, str, Any],
    listening: FromDishka[ListeningStats],
    days: Annotated[int, QueryParameter(ge=1, le=365)] = 30,
) -> UsStats:
    return await listening.us(request.user.id, days)


router = Router("/api", route_handlers=[stats, stats_us], exception_handlers=domain_errors(ERRORS))
