import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from muse.app import create_app
from muse.settings import Settings, load_settings
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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="muse")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the HTTP server")
    database = commands.add_parser("db", help="manage the user database")
    database.add_subparsers(dest="action", required=True).add_parser(
        "upgrade", help="create or migrate the user database"
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure_logging()
    settings = load_settings()
    if args.command == "serve":
        serve(settings)
    else:
        upgrade_database(settings.paths.user_db)
    return 0
