from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    pass


class EventBus:
    def __init__(self) -> None:
        self._handlers: defaultdict[type[Event], list[Callable[[Any], Awaitable[None]]]] = (
            defaultdict(list)
        )

    def subscribe[E: Event](
        self, event_type: type[E], handler: Callable[[E], Awaitable[None]]
    ) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        for handler in self._handlers.get(type(event), ()):
            await handler(event)
