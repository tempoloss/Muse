from collections.abc import AsyncIterator

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.settings import Settings
from tests.server.support import ORIGIN, ManualClock, ManualClockProvider

NOW_MS = 1_768_651_200_000


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(NOW_MS)


@pytest.fixture
async def app(settings: Settings, clock: ManualClock) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[ManualClockProvider(clock)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application
