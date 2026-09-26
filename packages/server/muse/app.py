from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from dishka import AsyncContainer, Provider, make_async_container
from dishka.integrations.litestar import LitestarProvider, setup_dishka
from litestar import Litestar

from muse.http.errors import EXCEPTION_HANDLERS
from muse.http.policy import HttpPolicy
from muse.http.spa import spa
from muse.settings import Settings
from muse.shared.tasks import BackgroundRunner
from muse.wiring.core import CoreProvider


def lifespan(container: AsyncContainer) -> Callable[[Litestar], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def run(_: Litestar) -> AsyncIterator[None]:
        runner = await container.get(BackgroundRunner)
        async with runner.running():
            yield

    return run


def create_app(settings: Settings, providers: Sequence[Provider] = ()) -> Litestar:
    container = make_async_container(CoreProvider(settings), LitestarProvider(), *providers)
    app = Litestar(
        route_handlers=[spa],
        exception_handlers=EXCEPTION_HANDLERS,
        openapi_config=None,
        lifespan=[lifespan(container)],
        on_shutdown=[container.close],
        logging_config=None,
    )
    app.asgi_handler = HttpPolicy(
        app.asgi_handler, origins=settings.http.origins, public_host=settings.http.public_host
    )
    setup_dishka(container, app)
    return app
