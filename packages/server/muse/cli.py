import argparse
import getpass
import json
import sqlite3
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from alembic import command
from alembic.config import Config
from dishka import make_async_container

from muse.app import app_providers, create_app
from muse.daily.service import DailyMaker
from muse.identity.domain import InvalidUsersError
from muse.identity.infra.users_file import UsersFile
from muse.identity.service import PasswordService
from muse.settings import Settings, load_settings
from muse.shared.errors import DomainError
from muse.shared.logging import configure_logging

MIGRATIONS = "muse:migrations"
DAILY_REMOTE = "daily-remote"
AGENT_PREFIX = "MUSE:"


def upgrade_database(user_db: Path) -> None:
    user_db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(user_db)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()
    config = Config()
    config.set_main_option("script_location", MIGRATIONS)
    config.attributes["database"] = user_db
    command.upgrade(config, "head")


def serve(settings: Settings) -> None:
    uvicorn.run(
        create_app(settings, jobs=True),
        host=settings.http.host,
        port=settings.http.port,
        log_level="warning",
        server_header=False,
    )


def set_password(settings: Settings, user_id: str, *, random: bool) -> int:
    users = UsersFile(settings.paths.users_file)
    if users.load().get(user_id) is None:
        raise InvalidUsersError(f"no such user: {user_id}")
    service = PasswordService(users)
    if random:
        sys.stdout.write(f"password for {user_id}: {service.set_random(user_id)}\n")
        return 0
    password = getpass.getpass(f"new password for {user_id}: ")
    if password != getpass.getpass("repeat: "):
        raise InvalidUsersError("passwords differ")
    service.set(user_id, password)
    sys.stdout.write(f"password for {user_id} saved\n")
    return 0


def iso_day(value: str) -> date:
    try:
        day = date.fromisoformat(value)
    except ValueError:
        day = None
    if day is None or day.isoformat() != value:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD day: {value!r}")
    return day


def tell_agent(message: dict[str, object]) -> None:
    sys.stdout.write(AGENT_PREFIX + json.dumps(message) + "\n")
    sys.stdout.flush()


async def agent_message() -> dict[str, Any] | None:
    line = await anyio.to_thread.run_sync(sys.stdin.readline)
    if not line:
        return None
    message = json.loads(line)
    return None if message.get("done") else message


async def agent_replies(prompt: str) -> AsyncIterator[tuple[str, str]]:
    tell_agent({"state": "prompt", "prompt": prompt})
    while (message := await agent_message()) is not None:
        yield message["model"], message["reply"]
        tell_agent({"state": "next"})


async def daily_remote(settings: Settings, day: date) -> int:
    container = make_async_container(*app_providers(settings))
    try:
        async with container() as request:
            maker = await request.get(DailyMaker)
            if await maker.exists(day):
                tell_agent({"state": "exists"})
                return 0
            saved = await maker.make(day, agent_replies)
    finally:
        await container.close()
    tell_agent({"state": "saved" if saved else "failed"})
    return 0 if saved else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="muse")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the HTTP server")
    database = commands.add_parser("db", help="manage the user database")
    database.add_subparsers(dest="action", required=True).add_parser(
        "upgrade", help="create or migrate the user database"
    )
    passwd = commands.add_parser("passwd", help="set a user's password in users.json")
    passwd.add_argument("user")
    passwd.add_argument("--random", action="store_true", help="generate and print a password")
    daily = commands.add_parser(DAILY_REMOTE, help="make a day's playlists from agent replies")
    daily.add_argument("day", type=iso_day)
    return root


def run(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "serve":
        serve(settings)
        return 0
    if args.command == "passwd":
        return set_password(settings, args.user, random=args.random)
    if args.command == DAILY_REMOTE:
        return anyio.run(daily_remote, settings, args.day)
    upgrade_database(settings.paths.user_db)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(sys.stderr if args.command == DAILY_REMOTE else None)
    try:
        return run(args, load_settings())
    except (InvalidUsersError, DomainError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
