from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
import structlog
from anyio.abc import TaskGroup

log = structlog.get_logger()


class BackgroundRunner:
    def __init__(self) -> None:
        self._group: TaskGroup | None = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        async with anyio.create_task_group() as group:
            self._group = group
            try:
                yield
            finally:
                self._group = None
                group.cancel_scope.cancel()

    def spawn[*A](self, fn: Callable[[*A], Awaitable[None]], *args: *A, name: str) -> None:
        if self._group is None:
            raise RuntimeError("the background runner is not running")
        self._group.start_soon(self._guarded, fn, args, name, name=name)

    async def _guarded[*A](
        self, fn: Callable[[*A], Awaitable[None]], args: tuple[*A], name: str
    ) -> None:
        try:
            await fn(*args)
        except Exception:
            log.exception("background task failed", task=name)
