from typing import Annotated, Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get
from litestar.params import FromPath, FromQuery, QueryParameter

from muse.catalog.domain import NO_SUCH_GENRE, NO_TRACK
from muse.discovery.domain import RADIO_MAX, RADIO_MIN, RADIO_SIZE, excluded_ids
from muse.discovery.service import Mixes, Radio
from muse.identity.domain import User
from muse.shared.errors import domain_errors

ERRORS = {NO_TRACK: 404, NO_SUCH_GENRE: 404}


@get("/radio/{tid:int}")
@inject
async def radio(
    tid: FromPath[int],
    request: Request[User, str, Any],
    service: FromDishka[Radio],
    exclude: FromQuery[str] = "",
    n: Annotated[int, QueryParameter(ge=RADIO_MIN, le=RADIO_MAX)] = RADIO_SIZE,
) -> dict[str, Any]:
    tracks = await service.tracks(request.user.id, tid, excluded_ids(exclude), n)
    return {"seed": tid, "tracks": tracks}


@get("/mix/{genre:str}")
@inject
async def mix(
    genre: FromPath[str], request: Request[User, str, Any], mixes: FromDishka[Mixes]
) -> dict[str, Any]:
    return await mixes.genre_mix(request.user.id, genre)


router = Router("/api", route_handlers=[radio, mix], exception_handlers=domain_errors(ERRORS))
