import argparse
import errno
import logging
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import NoReturn
from zoneinfo import ZoneInfo

from muse_agent import settings
from muse_agent.backup import backup_path, pull_backup
from muse_agent.daily import run_daily
from muse_agent.publish import publish
from muse_agent.settings import AgentConfig, ConfigError

INSTANCE_ADDRESS = ("127.0.0.1", 4536)
TICK_S = 60
SETTLED = ("saved", "exists")
LOG_NAME = "agent.log"
LOG_MAX_BYTES = 1 << 20
LOG_BACKUPS = 3

type Clock = Callable[[], datetime]

log = logging.getLogger("muse_agent")


@dataclass(frozen=True)
class Jobs:
    publish: Callable[[], object]
    daily: Callable[[date], str]
    backup: Callable[[date], object]
    has_backup: Callable[[date], bool]


@dataclass
class Scheduler:
    timezone: ZoneInfo
    daily_hour: int
    publish_every_s: int
    retry_s: int
    next_publish: float = 0.0
    settled_day: date | None = None
    next_daily: float = 0.0
    next_backup: float = 0.0

    def tick(self, clock: Clock, jobs: Jobs) -> None:
        self.publish_when_due(clock, jobs)
        self.daily_when_due(clock, jobs)
        self.backup_when_due(clock, jobs)

    def publish_when_due(self, clock: Clock, jobs: Jobs) -> None:
        started = clock().timestamp()
        if started < self.next_publish:
            return
        self.next_publish = started + self.publish_every_s
        attempt("publish", jobs.publish)

    def daily_when_due(self, clock: Clock, jobs: Jobs) -> None:
        now = clock()
        local = now.astimezone(self.timezone)
        day = local.date()
        if local.hour < self.daily_hour or day == self.settled_day:
            return
        if now.timestamp() < self.next_daily:
            return
        if attempt("daily", lambda: jobs.daily(day)) in SETTLED:
            self.settled_day = day
        else:
            self.next_daily = clock().timestamp() + self.retry_s

    def backup_when_due(self, clock: Clock, jobs: Jobs) -> None:
        now = clock()
        day = now.astimezone(self.timezone).date()
        if now.timestamp() < self.next_backup or jobs.has_backup(day):
            return
        if attempt("backup", lambda: jobs.backup(day)) is None:
            self.next_backup = clock().timestamp() + self.retry_s


def attempt[T](name: str, job: Callable[[], T]) -> T | None:
    try:
        return job()
    except Exception:
        log.exception("%s failed", name)
        return None


def agent_jobs(cfg: AgentConfig) -> Jobs:
    return Jobs(
        publish=lambda: publish(cfg),
        daily=lambda day: run_daily(cfg, day),
        backup=lambda day: pull_backup(cfg, day),
        has_backup=lambda day: backup_path(cfg, day).exists(),
    )


def run_forever(cfg: AgentConfig) -> NoReturn:
    scheduler = Scheduler(
        timezone=cfg.daily.timezone,
        daily_hour=cfg.daily.hour,
        publish_every_s=cfg.schedule.publish_every_s,
        retry_s=cfg.daily.retry_s,
    )
    jobs = agent_jobs(cfg)
    log.info("agent: running")
    while True:
        scheduler.tick(lambda: datetime.now(UTC), jobs)
        time.sleep(TICK_S)


def claim_instance() -> socket.socket | None:
    instance = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        instance.bind(INSTANCE_ADDRESS)
    except OSError as error:
        instance.close()
        if error.errno == errno.EADDRINUSE:
            return None
        raise
    return instance


def run_agent(cfg: AgentConfig) -> int:
    try:
        instance = claim_instance()
    except OSError:
        log.exception("agent: cannot claim %s:%d", *INSTANCE_ADDRESS)
        return 1
    if instance is None:
        return 0
    with instance:
        run_forever(cfg)


def local_today(cfg: AgentConfig) -> date:
    return datetime.now(cfg.daily.timezone).date()


def publish_command(cfg: AgentConfig, args: argparse.Namespace) -> int:
    return 0 if publish(cfg, allow_deletes=args.allow_deletes) else 1


def daily_command(cfg: AgentConfig, args: argparse.Namespace) -> int:
    return 0 if run_daily(cfg, args.day or local_today(cfg)) in SETTLED else 1


def backup_command(cfg: AgentConfig, args: argparse.Namespace) -> int:
    pull_backup(cfg, local_today(cfg))
    return 0


ONE_SHOT_COMMANDS: dict[str, Callable[[AgentConfig, argparse.Namespace], int]] = {
    "publish": publish_command,
    "daily": daily_command,
    "backup": backup_command,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muse-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="publish, make daily playlists and pull backups on schedule")
    publishing = commands.add_parser("publish", help="sync the library and upload the catalog")
    publishing.add_argument("--allow-deletes", action="store_true")
    daily = commands.add_parser("daily", help="make a day's playlists on the server")
    daily.add_argument("--day", type=date.fromisoformat, metavar="YYYY-MM-DD")
    commands.add_parser("backup", help="pull today's backup from the server")
    return parser


def configure_logging(work_dir: Path, console: bool) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            work_dir / LOG_NAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
            delay=True,
        )
    ]
    if console:
        handlers.append(logging.StreamHandler())
    formatter = logging.Formatter("%(asctime)s %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cfg = settings.load()
    except ConfigError as error:
        parser.exit(2, f"muse-agent: {error}\n")
    configure_logging(cfg.paths.work_dir, console=args.command != "run")
    if args.command == "run":
        return run_agent(cfg)
    try:
        return ONE_SHOT_COMMANDS[args.command](cfg, args)
    except Exception:
        log.exception("%s failed", args.command)
        return 1
