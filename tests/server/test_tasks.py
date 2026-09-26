import anyio
import pytest
from structlog.testing import capture_logs

from muse.shared.tasks import BackgroundRunner


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
