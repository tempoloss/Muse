from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import anyio
import structlog
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
from muse.insights.routes import router as insights
from muse.notifications.routes import router as notifications
from muse.pet.domain import HUNGER_CHECK_S
from muse.pet.routes import router as pet
from muse.pet.service import HungerWatch
from muse.settings import Settings
from muse.shared.tasks import BackgroundRunner
from muse.together.routes import router as together
from muse.wiring.contexts import ContextsProvider
from muse.wiring.core import CoreProvider
from muse.wiring.events import EventsProvider

ROUTERS = (identity, catalog, artwork, activity, notifications, pet, together, insights)

log = structlog.get_logger()


async def watch_hunger(container: AsyncContainer) -> None:
    while True:
        await anyio.sleep(HUNGER_CHECK_S)
        try:
            async with container() as request:
                await (await request.get(HungerWatch)).check()
        except Exception:
            log.exception("pet: hunger check failed")


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
                runner.spawn(watch_hunger, container, name="pet")
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
