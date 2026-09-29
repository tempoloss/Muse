from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, delete, get, post, put
from litestar.params import FromPath

from muse.activity.domain import BAD_SOURCE, LISTENED_OUT_OF_RANGE, Play
from muse.activity.schemas import PlayBody
from muse.activity.service import Likes, Plays
from muse.identity.domain import User
from muse.shared.errors import domain_errors

ERRORS = {"no track": 404, LISTENED_OUT_OF_RANGE: 422, BAD_SOURCE: 422}


@post("/plays", status_code=204)
@inject
async def report_play(
    data: PlayBody, request: Request[User, str, Any], plays: FromDishka[Plays]
) -> None:
    play = Play(
        track_id=data.track_id,
        started_at=data.started_at,
        listened_ms=data.listened_ms,
        completed=data.completed,
        skipped=data.skipped,
        source=data.source,
    )
    await plays.record(request.user.id, play)


@put("/likes/{tid:int}", status_code=204)
@inject
async def like(
    tid: FromPath[int], request: Request[User, str, Any], likes: FromDishka[Likes]
) -> None:
    await likes.like(request.user.id, tid)


@delete("/likes/{tid:int}", status_code=204)
@inject
async def unlike(
    tid: FromPath[int], request: Request[User, str, Any], likes: FromDishka[Likes]
) -> None:
    await likes.unlike(request.user.id, tid)


@get("/likes")
@inject
async def liked(request: Request[User, str, Any], likes: FromDishka[Likes]) -> dict[str, list[int]]:
    return await likes.listing(request.user.id)


router = Router(
    "/api",
    route_handlers=[report_play, like, unlike, liked],
    exception_handlers=domain_errors(ERRORS),
)
