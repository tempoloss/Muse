from dataclasses import dataclass

import pytest

from muse.shared.events import Event, EventBus


@dataclass(frozen=True, slots=True)
class Played(Event):
    track_id: int


@dataclass(frozen=True, slots=True)
class Liked(Event):
    track_id: int


async def test_handlers_run_in_registration_order_for_their_event_only() -> None:
    bus = EventBus()
    seen: list[tuple[str, int]] = []

    async def first(event: Played) -> None:
        seen.append(("first", event.track_id))

    async def second(event: Played) -> None:
        seen.append(("second", event.track_id))

    async def liked(event: Liked) -> None:
        seen.append(("liked", event.track_id))

    bus.subscribe(Played, first)
    bus.subscribe(Liked, liked)
    bus.subscribe(Played, second)
    await bus.publish(Played(track_id=7))

    assert seen == [("first", 7), ("second", 7)]


async def test_a_failing_handler_stops_the_publisher() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def broken(_: Played) -> None:
        raise RuntimeError("pet table missing")

    async def later(_: Played) -> None:
        seen.append("later")

    bus.subscribe(Played, broken)
    bus.subscribe(Played, later)

    with pytest.raises(RuntimeError, match="pet table missing"):
        await bus.publish(Played(track_id=1))
    assert seen == []
