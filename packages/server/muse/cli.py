import argparse
import getpass
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from muse.app import create_app
from muse.identity.domain import InvalidUsersError
from muse.identity.infra.users_file import UsersFile
from muse.identity.service import PasswordService
from muse.settings import Settings, load_settings
from muse.shared.errors import DomainError
from muse.shared.logging import configure_logging

MIGRATIONS = "muse:migrations"


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
        create_app(settings),
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
    return root


def run(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "serve":
        serve(settings)
        return 0
    if args.command == "passwd":
        return set_password(settings, args.user, random=args.random)
    upgrade_database(settings.paths.user_db)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging()
    try:
        return run(args, load_settings())
    except (InvalidUsersError, DomainError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
