from typing import Any

from dishka import AsyncContainer
from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.middleware import AbstractAuthenticationMiddleware, AuthenticationResult

from muse.http.policy import RENEW_STATE_KEY
from muse.identity.domain import SESSION_COOKIE
from muse.identity.service import SessionService
from muse.shared.errors import DomainError


class SessionAuthMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(
        self, connection: ASGIConnection[Any, Any, Any, Any]
    ) -> AuthenticationResult:
        token = connection.cookies.get(SESSION_COOKIE)
        container: AsyncContainer = connection.app.state.dishka_container
        async with container() as scope:
            service = await scope.get(SessionService)
            try:
                user, renew = await service.authenticate(token)
            except DomainError as error:
                raise NotAuthorizedException(detail=error.code) from error
        if renew and token:
            connection.scope["state"][RENEW_STATE_KEY] = token
        return AuthenticationResult(user=user, auth=token)
