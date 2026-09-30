from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get, post

from muse.diagnostics.schemas import PlayerLogBody
from muse.diagnostics.service import PlayerLogService
from muse.identity.domain import User


@get("/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@post("/player-log", status_code=204)
@inject
async def player_log(
    data: PlayerLogBody,
    request: Request[User, str, Any],
    service: FromDishka[PlayerLogService],
) -> None:
    user_agent = request.headers.get("user-agent", "")
    await service.record(request.user.id, user_agent, data.event, data.track_id)


router = Router("/api", route_handlers=[ping, player_log])
