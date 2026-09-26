import sqlite3
from pathlib import Path

import pytest

from muse.cli import main, upgrade_database

UNVERSIONED_SCHEMA = (
    Path(__file__).resolve().parents[1] / "fixtures" / "unversioned_user_schema.sql"
)
CONFIG = """
[paths]
data_dir = "{data}"
library_dir = "{data}/lib"
catalog_db = "{data}/state.sqlite"
web_dir = "{data}/web"

[http]
public_host = "music.example.org"
origins = ["https://music.example.org"]

[push]
enabled = false
"""


def structure(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT IN ('alembic_version', 'sqlite_sequence') ORDER BY name"
            )
        ]
        indexes = connection.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' "
            "AND tbl_name <> 'alembic_version' ORDER BY name"
        ).fetchall()
        columns = {
            name: connection.execute(f"PRAGMA table_info({name})").fetchall() for name in tables
        }
    finally:
        connection.close()
    return {"columns": columns, "indexes": indexes}


def unversioned_database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(UNVERSIONED_SCHEMA.read_text(encoding="utf-8"))
    connection.close()
    return path


def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_a_fresh_database_matches_the_unversioned_schema(tmp_path: Path) -> None:
    fresh = tmp_path / "data" / "muse.sqlite"

    upgrade_database(fresh)

    assert structure(fresh) == structure(unversioned_database(tmp_path / "unversioned.sqlite"))
    assert query(fresh, "PRAGMA journal_mode") == [("wal",)]
    assert query(fresh, "SELECT id, food, joy, energy, clean, sick FROM pet") == [
        (1, 80.0, 80.0, 80.0, 80.0, 0)
    ]
    assert query(fresh, "SELECT version_num FROM alembic_version") == [("0001",)]


def test_upgrading_an_unversioned_database_keeps_every_row(tmp_path: Path) -> None:
    path = unversioned_database(tmp_path / "muse.sqlite")
    connection = sqlite3.connect(path)
    connection.executescript(
        "INSERT INTO pet(id,name,born_at,food,joy,energy,clean,updated_at) "
        "VALUES (1,'Пушок',10,12.5,40,60,70,20);"
        "INSERT INTO plays VALUES ('alice', 7, 1000, 40000, 1, 0, 'album:3');"
        "INSERT INTO likes VALUES ('bob', 7, 2000);"
        "INSERT INTO sessions VALUES ('hash', 'alice', 1, 2, 3, 'ua');"
    )
    connection.close()

    upgrade_database(path)
    upgrade_database(path)

    assert query(path, "SELECT name, food, updated_at FROM pet") == [("Пушок", 12.5, 20)]
    assert query(path, "SELECT * FROM plays") == [("alice", 7, 1000, 40000, 1, 0, "album:3")]
    assert query(path, "SELECT * FROM likes") == [("bob", 7, 2000)]
    assert query(path, "SELECT user FROM sessions") == [("alice",)]
    assert query(path, "SELECT version_num FROM alembic_version") == [("0001",)]


def test_the_cli_upgrades_the_configured_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "muse.toml"
    config.write_text(CONFIG.format(data=(tmp_path / "data").as_posix()), encoding="utf-8")
    monkeypatch.setenv("MUSE_CONFIG", str(config))

    assert main(["db", "upgrade"]) == 0

    assert query(tmp_path / "data" / "muse.sqlite", "SELECT COUNT(*) FROM pet") == [(1,)]
