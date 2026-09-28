import sqlite3
from contextlib import closing
from typing import Any

from tests.fixtures.catalog import FixtureCatalog


def fixture_rows(library: FixtureCatalog, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    with closing(sqlite3.connect(f"file:{library.catalog_db.as_posix()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def identity(library: FixtureCatalog) -> dict[str, str]:
    canonical = {
        row["name"]: row["canonical"]
        for row in fixture_rows(library, "SELECT name, canonical FROM artists")
    }
    tags = {row["artist"] for row in fixture_rows(library, "SELECT DISTINCT artist FROM tracks")}
    return {tag: canonical.get(tag) or tag for tag in tags}
