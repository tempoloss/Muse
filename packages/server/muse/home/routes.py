from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get

from muse.home.service import HomeFeed
from muse.identity.domain import User


@get("/home")
@inject
async def home(request: Request[User, str, Any], feed: FromDishka[HomeFeed]) -> dict[str, Any]:
    return await feed.home(request.user.id)


router = Router("/api", route_handlers=[home])
