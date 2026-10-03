import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SQLITE_SIDE_FILES = ("", "-journal", "-wal", "-shm")
DRIVE = re.compile(r"^[A-Za-z]:/")


class SnapshotError(Exception):
    pass


@dataclass(frozen=True)
class SnapshotStats:
    rows: int
    rewritten: int
    missing: int


def make_snapshot(catalog_db: Path, library_dir: Path, out: Path) -> SnapshotStats:
    temp = out.with_name(f"{out.name}.tmp")
    discard(temp)
    try:
        with closing(sqlite3.connect(temp)) as copy:
            copy_live(catalog_db, copy)
            mode = copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode != "delete":
                raise SnapshotError(f"journal mode stayed {mode}")
            stats = relocate_tracks(copy, library_dir, disk_names(library_dir))
            copy.commit()
            verdict = copy.execute("PRAGMA integrity_check").fetchall()
        if verdict != [("ok",)]:
            raise SnapshotError(f"integrity check failed: {verdict[:3]}")
        temp.replace(out)
    except BaseException:
        discard(temp)
        raise
    return stats


def copy_live(catalog_db: Path, copy: sqlite3.Connection) -> None:
    uri = f"{catalog_db.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as live:
        live.backup(copy)


def disk_names(library_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for folder, _, files in os.walk(library_dir):
        base = Path(folder).relative_to(library_dir)
        for name in files:
            relative = (base / name).as_posix()
            names[relative.casefold()] = relative
    return names


def relocate_tracks(
    db: sqlite3.Connection, library_dir: Path, on_disk: dict[str, str]
) -> SnapshotStats:
    root = library_dir.as_posix().rstrip("/") + "/"
    query = "SELECT id, path, status FROM tracks WHERE path IS NOT NULL"
    rows = db.execute(query).fetchall()
    changes: list[tuple[str | None, int]] = []
    missing = 0
    for track_id, stored, status in rows:
        relative = library_relative(stored, root)
        found = on_disk.get(relative.casefold()) if relative is not None else None
        if found is None and status == "ok":
            missing += 1
        relocated = found or relative
        if relocated != stored:
            changes.append((relocated, track_id))
    db.executemany("UPDATE tracks SET path = ? WHERE id = ?", changes)
    return SnapshotStats(rows=len(rows), rewritten=len(changes), missing=missing)


def library_relative(stored: str, root: str) -> str | None:
    path = stored.replace("\\", "/")
    if path[: len(root)].casefold() == root.casefold():
        return path[len(root) :]
    if path.startswith("/") or DRIVE.match(path):
        return None
    return path


def discard(database: Path) -> None:
    for suffix in SQLITE_SIDE_FILES:
        database.with_name(database.name + suffix).unlink(missing_ok=True)
