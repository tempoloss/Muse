from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Response, Router, get, post
from litestar.datastructures import Cookie

from muse.identity.domain import (
    SESSION_COOKIE,
    SESSION_TTL_S,
    Me,
    TooManyAttemptsError,
    User,
    Users,
)
from muse.identity.schemas import LoginBody
from muse.identity.service import LoginService, SessionService
from muse.shared.errors import detail_response, domain_errors

ERRORS = {"bad credentials": 401, "unauthorized": 401}


def session_cookie(token: str, max_age: int) -> Cookie:
    return Cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def client_address(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip")
    return forwarded or (request.client.host if request.client else "?")


@post("/login", opt={"skip_auth": True}, status_code=200)
@inject
async def login(
    data: LoginBody, request: Request, service: FromDishka[LoginService]
) -> Response[Me]:
    result = await service.login(
        data.login, data.password, client_address(request), request.headers.get("user-agent", "")
    )
    return Response(result.me, cookies=[session_cookie(result.token, SESSION_TTL_S)])


@post("/logout", opt={"skip_auth": True}, status_code=204)
@inject
async def logout(request: Request, service: FromDishka[SessionService]) -> Response[None]:
    if token := request.cookies.get(SESSION_COOKIE):
        await service.logout(token)
    return Response(None, status_code=204, cookies=[session_cookie("", 0)])


@get("/me")
@inject
async def me(request: Request[User, str, Any], users: FromDishka[Users]) -> Me:
    return users.me(request.user)


def too_many_attempts(_: Request, error: TooManyAttemptsError) -> Response[dict[str, object]]:
    return detail_response(429, error.code, {"Retry-After": str(error.retry_after)})


router = Router(
    "/api",
    route_handlers=[login, logout, me],
    exception_handlers={**domain_errors(ERRORS), TooManyAttemptsError: too_many_attempts},
)
