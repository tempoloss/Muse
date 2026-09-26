import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config

from muse.settings import load_settings

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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="muse")
    commands = root.add_subparsers(dest="command", required=True)
    database = commands.add_parser("db", help="manage the user database")
    database.add_subparsers(dest="action", required=True).add_parser(
        "upgrade", help="create or migrate the user database"
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    parser().parse_args(argv)
    settings = load_settings()
    upgrade_database(settings.paths.user_db)
    return 0
