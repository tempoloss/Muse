from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from dishka import AsyncContainer, Provider, make_async_container
from dishka.integrations.litestar import LitestarProvider, setup_dishka
from litestar import Litestar
from litestar.middleware import DefineMiddleware

from muse.activity.routes import router as activity
from muse.artwork.routes import router as artwork
from muse.artwork.service import Artwork
from muse.catalog.routes import router as catalog
from muse.http.auth import SessionAuthMiddleware
from muse.http.errors import EXCEPTION_HANDLERS
from muse.http.policy import HttpPolicy
from muse.http.spa import api_not_found, spa
from muse.identity.domain import Users
from muse.identity.routes import router as identity
from muse.notifications.routes import router as notifications
from muse.settings import Settings
from muse.shared.tasks import BackgroundRunner
from muse.wiring.contexts import ContextsProvider
from muse.wiring.core import CoreProvider
from muse.wiring.events import EventsProvider

ROUTERS = (identity, catalog, artwork, activity, notifications)


def lifespan(
    container: AsyncContainer, *, jobs: bool
) -> Callable[[Litestar], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def run(_: Litestar) -> AsyncIterator[None]:
        await container.get(Users)
        runner = await container.get(BackgroundRunner)
        async with runner.running():
            if jobs:
                runner.spawn((await container.get(Artwork)).warm, name="artwork")
            yield

    return run


def create_app(
    settings: Settings, providers: Sequence[Provider] = (), *, jobs: bool = False
) -> Litestar:
    container = make_async_container(
        CoreProvider(settings), ContextsProvider(), EventsProvider(), LitestarProvider(), *providers
    )
    app = Litestar(
        route_handlers=[*ROUTERS, api_not_found, spa],
        middleware=[DefineMiddleware(SessionAuthMiddleware, exclude_from_auth_key="skip_auth")],
        exception_handlers=EXCEPTION_HANDLERS,
        openapi_config=None,
        lifespan=[lifespan(container, jobs=jobs)],
        on_shutdown=[container.close],
        logging_config=None,
    )
    app.asgi_handler = HttpPolicy(
        app.asgi_handler, origins=settings.http.origins, public_host=settings.http.public_host
    )
    setup_dishka(container, app)
    return app
