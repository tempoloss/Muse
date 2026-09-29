from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get, post, put
from litestar.params import FromPath

from muse.catalog.domain import NO_ALBUM
from muse.identity.domain import User
from muse.pet.domain import ASLEEP, BAD_NAME, DONE, HEALTHY, NO_SUCH_ACTION, TIRED, Row
from muse.pet.schemas import PetNameBody, QuestAlbumBody
from muse.pet.service import PetCare, QuestAlbums
from muse.shared.errors import domain_errors

ERRORS = {
    NO_SUCH_ACTION: 404,
    BAD_NAME: 422,
    ASLEEP: 409,
    TIRED: 409,
    HEALTHY: 409,
    NO_ALBUM: 404,
    DONE: 409,
}


@get("/pet")
@inject
async def pet(request: Request[User, str, Any], care: FromDishka[PetCare]) -> Row:
    return await care.show(request.user.id)


@put("/quest/album")
@inject
async def quest_album(
    data: QuestAlbumBody, request: Request[User, str, Any], albums: FromDishka[QuestAlbums]
) -> Row:
    return await albums.choose(request.user.id, data.album_id)


@put("/pet/name")
@inject
async def rename(
    data: PetNameBody, request: Request[User, str, Any], care: FromDishka[PetCare]
) -> Row:
    return await care.rename(request.user.id, data.name)


@post("/pet/{action:str}", status_code=200)
@inject
async def act(
    action: FromPath[str], request: Request[User, str, Any], care: FromDishka[PetCare]
) -> Row:
    return await care.act(request.user.id, action)


router = Router(
    "/api",
    route_handlers=[pet, quest_album, rename, act],
    exception_handlers=domain_errors(ERRORS),
)
