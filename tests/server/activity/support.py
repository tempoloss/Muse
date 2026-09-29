import sqlite3
from contextlib import closing
from pathlib import Path

NOW_MS = 1_800_000_000_000


def catalog_row(catalog_db: Path, sql: str) -> tuple[int, int]:
    with closing(sqlite3.connect(f"file:{catalog_db.as_posix()}?mode=ro", uri=True)) as db:
        return db.execute(sql).fetchone()
