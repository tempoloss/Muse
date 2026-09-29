from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get, post, put
from litestar.params import FromPath

from muse.identity.domain import User
from muse.pet.domain import ASLEEP, BAD_NAME, HEALTHY, NO_SUCH_ACTION, TIRED, Row
from muse.pet.schemas import PetNameBody
from muse.pet.service import PetCare
from muse.shared.errors import domain_errors

ERRORS = {NO_SUCH_ACTION: 404, BAD_NAME: 422, ASLEEP: 409, TIRED: 409, HEALTHY: 409}


@get("/pet")
@inject
async def pet(request: Request[User, str, Any], care: FromDishka[PetCare]) -> Row:
    return await care.show(request.user.id)


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


router = Router("/api", route_handlers=[pet, rename, act], exception_handlers=domain_errors(ERRORS))
