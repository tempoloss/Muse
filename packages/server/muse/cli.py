import argparse
import getpass
import json
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from dishka import make_async_container

from muse.app import app_providers, create_app
from muse.catalog.domain import Row
from muse.catalog.service import Catalog
from muse.daily.service import DailyMaker
from muse.identity.domain import InvalidUsersError, Users
from muse.identity.infra.users_file import UsersFile
from muse.identity.service import PasswordService
from muse.settings import Settings, load_settings
from muse.shared.errors import DomainError
from muse.shared.logging import configure_logging
from muse.userdb import (
    UserDatabaseError,
    database_problems,
    restore_database,
    snapshot_database,
    upgrade_database,
)

DAILY_REMOTE = "daily-remote"
AGENT_PREFIX = "MUSE:"
PLAYBACK_SAMPLE = 5
READ_BYTES = 4096


def database(settings: Settings, action: str) -> int:
    paths = settings.paths
    if action == "snapshot":
        snapshot_database(paths.user_db, paths.upgrade_snapshot)
    elif action == "restore":
        restore_database(paths.upgrade_snapshot, paths.user_db)
    else:
        upgrade_database(paths.user_db)
    return 0


def read_head(path: Path) -> bool:
    with path.open("rb") as audio:
        return bool(audio.read(READ_BYTES))


async def playable(catalog: Catalog, tracks: Sequence[Row]) -> bool:
    for track in tracks:
        try:
            path = await catalog.stream_file(track["id"])
            if await anyio.to_thread.run_sync(read_head, path):
                return True
        except DomainError, OSError:
            continue
    return False


async def health(settings: Settings) -> list[str]:
    problems = database_problems(settings.paths.user_db)
    container = make_async_container(*app_providers(settings))
    try:
        async with container() as request:
            catalog = await request.get(Catalog)
            tracks = await catalog.library_tracks()
            if not tracks:
                problems.append("the catalog has no playable tracks")
            elif not await playable(catalog, tracks[:PLAYBACK_SAMPLE]):
                problems.append(f"none of the first {PLAYBACK_SAMPLE} tracks has a readable file")
            users = await request.get(Users)
            report = f"{len(users.all)} users, {len(tracks)} playable tracks"
    finally:
        await container.close()
    if not problems:
        sys.stdout.write(f"ok: {report}\n")
    return problems


def check(settings: Settings) -> int:
    problems = anyio.run(health, settings)
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    return 1 if problems else 0


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
    actions = commands.add_parser("db", help="manage the user database").add_subparsers(
        dest="action", required=True
    )
    actions.add_parser("upgrade", help="create or migrate the user database")
    actions.add_parser("snapshot", help="save the user database before an upgrade")
    actions.add_parser("restore", help="put back the database saved by snapshot")
    commands.add_parser("check", help="check the user database, the catalog and the track files")
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
    if args.command == "check":
        return check(settings)
    return database(settings, args.action)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging(sys.stderr if args.command == DAILY_REMOTE else None)
    try:
        return run(args, load_settings())
    except (InvalidUsersError, DomainError, UserDatabaseError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
