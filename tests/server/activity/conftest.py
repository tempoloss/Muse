from collections.abc import AsyncIterator

import pytest
from dishka import Provider, Scope, decorate
from litestar import Litestar
from litestar.testing import AsyncTestClient

from muse.activity.domain import LikeChanged, PlayRecorded
from muse.app import create_app
from muse.settings import Settings
from muse.shared.events import Event, EventBus
from tests.server.activity.support import NOW_MS, catalog_row
from tests.server.support import ORIGIN, ManualClock, ManualClockProvider


class RecordedEvents(Provider):
    scope = Scope.REQUEST

    def __init__(self, seen: list[Event]) -> None:
        super().__init__()
        self.seen = seen

    async def record(self, event: Event) -> None:
        self.seen.append(event)

    @decorate
    def recording(self, bus: EventBus) -> EventBus:
        bus.subscribe(PlayRecorded, self.record)
        bus.subscribe(LikeChanged, self.record)
        return bus


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(NOW_MS)


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
async def app(
    settings: Settings, clock: ManualClock, events: list[Event]
) -> AsyncIterator[Litestar]:
    application = create_app(
        settings, providers=[ManualClockProvider(clock), RecordedEvents(events)]
    )
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


@pytest.fixture
def long_track(settings: Settings) -> tuple[int, int]:
    return catalog_row(
        settings.paths.catalog_db,
        "SELECT id, dur FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT 1",
    )


@pytest.fixture
def other_track(settings: Settings, long_track: tuple[int, int]) -> int:
    return catalog_row(
        settings.paths.catalog_db,
        f"SELECT id, dur FROM tracks WHERE status='ok' AND id<>{long_track[0]} ORDER BY id LIMIT 1",
    )[0]
