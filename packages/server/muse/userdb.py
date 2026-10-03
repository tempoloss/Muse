import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS = "muse:migrations"
REVISION = "SELECT version_num FROM alembic_version"


class UserDatabaseError(Exception):
    pass


def migrations() -> Config:
    config = Config()
    config.set_main_option("script_location", MIGRATIONS)
    return config


def upgrade_database(user_db: Path) -> None:
    user_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(user_db)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    config = migrations()
    config.attributes["database"] = user_db
    command.upgrade(config, "head")


def head_revision() -> str | None:
    return ScriptDirectory.from_config(migrations()).get_current_head()


def copy_database(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source)) as origin, closing(sqlite3.connect(target)) as copy:
        origin.backup(copy)


def snapshot_database(user_db: Path, snapshot: Path) -> None:
    if not user_db.is_file():
        raise UserDatabaseError(f"no user database at {user_db}")
    partial = snapshot.with_name(f"{snapshot.name}.part")
    partial.unlink(missing_ok=True)
    mode = stat.S_IMODE(user_db.stat().st_mode)
    os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode))
    partial.chmod(mode)
    copy_database(user_db, partial)
    partial.replace(snapshot)


def restore_database(snapshot: Path, user_db: Path) -> None:
    if not snapshot.is_file():
        raise UserDatabaseError(f"no snapshot at {snapshot}")
    copy_database(snapshot, user_db)


def database_problems(user_db: Path) -> list[str]:
    if not user_db.is_file():
        return [f"no user database at {user_db}"]
    try:
        with closing(sqlite3.connect(user_db)) as connection:
            verdict = connection.execute("PRAGMA integrity_check").fetchall()
            revisions = [row[0] for row in connection.execute(REVISION)]
    except sqlite3.DatabaseError as error:
        return [f"user database: {error}"]
    problems = []
    if verdict != [("ok",)]:
        problems.append(f"user database fails the integrity check: {verdict[0][0]}")
    head = head_revision()
    if revisions != [head]:
        found = ", ".join(revisions) or "no revision"
        problems.append(f"user database is at {found}, this release expects {head}")
    return problems
