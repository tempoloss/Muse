import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from muse.settings import Settings
from tests.server.support import ManualClock

HOUR_MS = 3600 * 1000
DAY_MS = 24 * HOUR_MS
LETTERS_DAY = date(2026, 1, 17)
SHARED_LIKE_DAY = date(2026, 1, 18)
TOGETHER_DAY = date(2026, 1, 21)
SAME_ALBUM_DAY = date(2026, 1, 29)


def noon_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp() * 1000)


class PetTable:
    def __init__(self, user_db: Path, clock: ManualClock) -> None:
        self.user_db = user_db
        self.clock = clock

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with closing(sqlite3.connect(self.user_db)) as db:
            rows = db.execute(sql, params).fetchall()
            db.commit()
            return rows

    def reset(self, *, quest_paid: bool = True, **fields: Any) -> None:
        state = {"sick": 0, "asleep_until": None, "updated_at": self.clock.ms, **fields}
        assignments = ", ".join(f"{name}=?" for name in state)
        self.execute(f"UPDATE pet SET {assignments} WHERE id=1", tuple(state.values()))
        self.execute("DELETE FROM pet_log")
        if quest_paid:
            self.execute(
                "INSERT INTO pet_log(at, user, action, detail) VALUES (?, NULL, 'quest', ?)",
                (self.clock.ms, self.clock.today().isoformat()),
            )

    def row(self) -> dict[str, Any]:
        with closing(sqlite3.connect(self.user_db)) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute("SELECT * FROM pet").fetchone())

    def log(self, action: str) -> list[tuple[Any, ...]]:
        return self.execute(
            "SELECT user, detail FROM pet_log WHERE action=? ORDER BY id", (action,)
        )


def catalog_rows(
    settings: Settings, sql: str, params: tuple[Any, ...] = ()
) -> list[tuple[Any, ...]]:
    uri = f"file:{settings.paths.catalog_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(sql, params).fetchall()


def catalog_ids(settings: Settings, sql: str) -> list[int]:
    return [row[0] for row in catalog_rows(settings, sql)]


def play(track_id: int, listened_ms: int, started_at: int) -> dict[str, Any]:
    return {
        "track_id": track_id,
        "started_at": started_at,
        "listened_ms": listened_ms,
        "completed": False,
        "skipped": False,
        "source": "other",
    }
