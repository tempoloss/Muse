from collections.abc import AsyncIterator

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.settings import Settings
from tests.server.pet.support import LETTERS_DAY, PetTable, noon_ms
from tests.server.support import ORIGIN, ManualClock, ManualClockProvider


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(noon_ms(LETTERS_DAY))


@pytest.fixture
async def app(settings: Settings, clock: ManualClock) -> AsyncIterator[Litestar]:
    application = create_app(settings, providers=[ManualClockProvider(clock)])
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


@pytest.fixture
def pet_table(settings: Settings, clock: ManualClock) -> PetTable:
    return PetTable(settings.paths.user_db, clock)
