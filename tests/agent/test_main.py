import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from muse_agent.main import Jobs, Scheduler


class Clock:
    def __init__(self, moment: str) -> None:
        self.now = datetime.fromisoformat(moment)

    def __call__(self) -> datetime:
        return self.now

    def at(self, moment: str) -> None:
        self.now = datetime.fromisoformat(moment)


class Agent:
    def __init__(self, daily_results: list[str] | None = None) -> None:
        self.calls: list[tuple[str, date | None]] = []
        self.daily_results = daily_results or []
        self.failures: dict[str, int] = {}
        self.stored: set[date] = set()

    def job(self, name: str, day: date | None = None) -> None:
        self.calls.append((name, day))
        if self.failures.get(name, 0) > 0:
            self.failures[name] -= 1
            raise RuntimeError(f"{name} broke")

    def publish(self) -> bool:
        self.job("publish")
        return True

    def daily(self, day: date) -> str:
        self.job("daily", day)
        return self.daily_results.pop(0)

    def backup(self, day: date) -> date:
        self.job("backup", day)
        self.stored.add(day)
        return day

    def jobs(self) -> Jobs:
        return Jobs(
            publish=self.publish,
            daily=self.daily,
            backup=self.backup,
            has_backup=self.stored.__contains__,
        )

    def runs(self, name: str) -> list[date | None]:
        return [day for called, day in self.calls if called == name]


def scheduler(zone: str = "UTC") -> Scheduler:
    return Scheduler(timezone=ZoneInfo(zone), daily_hour=5, publish_every_s=600, retry_s=1800)


def test_publish_runs_at_once_and_then_once_per_interval() -> None:
    agent, clock, plan = Agent(["exists"]), Clock("2026-10-03T12:00:00+00:00"), scheduler()

    for moment in ("12:00:00", "12:05:00", "12:09:59", "12:10:00", "12:15:00", "12:20:00"):
        clock.at(f"2026-10-03T{moment}+00:00")
        plan.tick(clock, agent.jobs())

    assert len(agent.runs("publish")) == 3


@pytest.mark.parametrize(
    ("zone", "before", "at", "day"),
    [
        (
            "Asia/Tokyo",
            "2026-10-03T19:59:59+00:00",
            "2026-10-03T20:00:00+00:00",
            date(2026, 10, 4),
        ),
        (
            "Pacific/Auckland",
            "2026-10-03T15:59:59+00:00",
            "2026-10-03T16:00:00+00:00",
            date(2026, 10, 4),
        ),
    ],
)
def test_daily_waits_for_the_hour_in_the_configured_time_zone(
    zone: str, before: str, at: str, day: date
) -> None:
    agent, clock, plan = Agent(["saved"]), Clock(before), scheduler(zone)

    plan.tick(clock, agent.jobs())
    assert agent.runs("daily") == []

    clock.at(at)
    plan.tick(clock, agent.jobs())
    assert agent.runs("daily") == [day]
    assert agent.runs("backup") == [day]


def test_a_failed_daily_is_retried_after_the_cooldown_until_the_day_is_settled() -> None:
    agent, plan = Agent(["failed", "saved", "exists"]), scheduler()
    clock = Clock("2026-10-03T05:00:00+00:00")

    for moment in (
        "2026-10-03T05:00:00",
        "2026-10-03T05:29:59",
        "2026-10-03T05:30:00",
        "2026-10-03T23:00:00",
        "2026-10-04T04:59:59",
        "2026-10-04T05:00:00",
        "2026-10-04T05:40:00",
    ):
        clock.at(f"{moment}+00:00")
        plan.tick(clock, agent.jobs())

    assert agent.runs("daily") == [
        date(2026, 10, 3),
        date(2026, 10, 3),
        date(2026, 10, 4),
    ]


def test_a_job_that_raises_is_logged_and_the_tick_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent, clock, plan = Agent(["exists"]), Clock("2026-10-03T06:00:00+00:00"), scheduler()
    agent.failures["publish"] = 1

    with caplog.at_level(logging.INFO):
        plan.tick(clock, agent.jobs())

    assert [name for name, _ in agent.calls] == ["publish", "daily", "backup"]
    assert "publish failed" in caplog.messages
    assert "publish broke" in caplog.text


def test_a_raising_daily_counts_as_a_failure() -> None:
    agent, clock, plan = Agent(["saved"]), Clock("2026-10-03T06:00:00+00:00"), scheduler()
    agent.failures["daily"] = 1

    for moment in ("06:00:00", "06:10:00", "06:30:00", "06:40:00"):
        clock.at(f"2026-10-03T{moment}+00:00")
        plan.tick(clock, agent.jobs())

    assert agent.runs("daily") == [date(2026, 10, 3), date(2026, 10, 3)]


def test_a_missing_backup_is_pulled_with_a_cooldown_after_failures() -> None:
    agent, clock, plan = Agent(["exists"]), Clock("2026-10-03T00:30:00+00:00"), scheduler()
    agent.failures["backup"] = 1

    for moment in (
        "2026-10-03T00:30:00",
        "2026-10-03T00:59:59",
        "2026-10-03T01:00:00",
        "2026-10-03T01:30:00",
        "2026-10-04T00:00:00",
    ):
        clock.at(f"{moment}+00:00")
        plan.tick(clock, agent.jobs())

    assert agent.runs("backup") == [
        date(2026, 10, 3),
        date(2026, 10, 3),
        date(2026, 10, 4),
    ]
