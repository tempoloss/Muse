import anyio
import pytest
from structlog.testing import capture_logs

from muse.shared.tasks import BackgroundRunner, watch_loop


class StopError(Exception):
    pass


async def test_spawned_work_runs_while_the_caller_continues_and_failures_are_logged() -> None:
    runner = BackgroundRunner()
    delivered = anyio.Event()
    got: list[int] = []

    async def broken() -> None:
        raise RuntimeError("push service down")

    async def deliver(value: int) -> None:
        got.append(value)
        delivered.set()

    with capture_logs() as logs:
        async with runner.running():
            runner.spawn(broken, name="push")
            runner.spawn(deliver, 5, name="deliver")
            assert got == []
            with anyio.fail_after(2):
                await delivered.wait()

    assert got == [5]
    assert [(entry["event"], entry["task"]) for entry in logs] == [
        ("background task failed", "push")
    ]


async def test_leaving_the_runner_cancels_unfinished_work() -> None:
    runner = BackgroundRunner()
    started = anyio.Event()
    finished: list[bool] = []

    async def forever() -> None:
        started.set()
        await anyio.sleep(3600)
        finished.append(True)

    with anyio.fail_after(2):
        async with runner.running():
            runner.spawn(forever, name="forever")
            await started.wait()

    assert finished == []


async def test_spawning_needs_a_running_runner() -> None:
    async def noop() -> None:
        return None

    runner = BackgroundRunner()
    async with runner.running():
        runner.spawn(noop, name="inside")

    with pytest.raises(RuntimeError, match="not running"):
        runner.spawn(noop, name="outside")


async def test_only_a_wakeup_that_came_late_is_reported_as_a_blocked_loop() -> None:
    readings = iter([0.0, 0.5, 1.0, 1.52, 2.0, 3.9, 4.0])
    naps: list[float] = []

    async def nap(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) == 4:
            raise StopError

    with capture_logs() as logs, pytest.raises(StopError):
        await watch_loop(lambda: next(readings), nap)

    assert naps == [0.5] * 4
    assert [(entry["event"], entry["ms"]) for entry in logs] == [("event loop was blocked", 1400)]
