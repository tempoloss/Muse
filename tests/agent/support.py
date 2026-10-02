import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from muse_agent import settings
from muse_agent.settings import AgentConfig, Paths

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "agent.example.toml"
TRACKS = (
    "CREATE TABLE tracks(id INTEGER PRIMARY KEY AUTOINCREMENT, album_id INT, num INT, artist TEXT, "
    "album TEXT, title TEXT, dur INT, tier INT, status TEXT DEFAULT 'pending', path TEXT, err TEXT)"
)
STATUS_INDEX = "CREATE INDEX ix_tracks_status ON tracks(status)"


def agent_config(root: Path) -> AgentConfig:
    paths = Paths(
        library_dir=root / "lib",
        catalog_db=root / "state.sqlite",
        work_dir=root / "work",
    )
    paths.library_dir.mkdir(parents=True, exist_ok=True)
    paths.work_dir.mkdir(parents=True, exist_ok=True)
    return replace(settings.load(EXAMPLE), paths=paths)


def touch(library: Path, relative: str) -> None:
    path = library / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3")


def stored_path(library: Path, relative: str) -> str:
    return f"{library.as_posix()}/{relative}".replace("/", "\\")


def create_catalog(path: Path, rows: Sequence[tuple[str | None, str]]) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(TRACKS)
    db.execute(STATUS_INDEX)
    db.executemany("INSERT INTO tracks(path, status) VALUES (?, ?)", rows)
    db.commit()
    return db


def stored_paths(path: Path) -> list[str | None]:
    with closing(sqlite3.connect(path)) as db:
        return [row[0] for row in db.execute("SELECT path FROM tracks ORDER BY id")]


class FakeRclone:
    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> int:
        self.calls.append(list(argv))
        return self.codes.get(argv[1], 0)

    @property
    def verbs(self) -> list[str]:
        return [call[1] for call in self.calls]
