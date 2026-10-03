import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from muse_agent.snapshot import SnapshotError, SnapshotStats, make_snapshot
from tests.agent.support import create_catalog, stored_path, stored_paths, touch


def pragma(path: Path, name: str) -> str:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(f"PRAGMA {name}").fetchone()[0]


def damage_status_index(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        query = "SELECT rootpage FROM sqlite_master WHERE name = 'ix_tracks_status'"
        root = db.execute(query).fetchone()[0]
    data = bytearray(path.read_bytes())
    start = (root - 1) * page_size
    data[start : start + page_size] = data[start : start + page_size].replace(b"ok", b"ox")
    path.write_bytes(bytes(data))


def test_published_paths_are_library_relative_and_spelled_as_on_disk(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    touch(library, "Indie/X/a.mp3")
    touch(library, "Indie/X/b.mp3")
    rows = [
        (stored_path(library, "indie/x/a.mp3").lower(), "ok"),
        (stored_path(library, "Indie/X/b.mp3"), "ok"),
        (stored_path(library, "Rock/Gone/c.mp3"), "ok"),
        (stored_path(library, "Rock/Gone/d.mp3"), "fail"),
        ("E:\\elsewhere\\e.mp3", "ok"),
        ("Indie/X/a.mp3", "ok"),
        (f"{library.as_posix()}x/f.mp3", "ok"),
        (None, "pending"),
    ]
    source = tmp_path / "state.sqlite"
    out = tmp_path / "work" / "catalog-publish.sqlite"
    out.parent.mkdir()

    with closing(create_catalog(source, rows)):
        assert Path(f"{source}-wal").stat().st_size > 0
        stats = make_snapshot(source, library, out)
        source_paths = stored_paths(source)

    assert stats == SnapshotStats(rows=7, rewritten=6, missing=3)
    assert [path.name for path in out.parent.iterdir()] == ["catalog-publish.sqlite"]
    assert stored_paths(out) == [
        "Indie/X/a.mp3",
        "Indie/X/b.mp3",
        "Rock/Gone/c.mp3",
        "Rock/Gone/d.mp3",
        None,
        "Indie/X/a.mp3",
        None,
        None,
    ]
    assert pragma(out, "journal_mode") == "delete"
    assert pragma(out, "integrity_check") == "ok"
    assert source_paths == [path for path, _ in rows]
    assert pragma(source, "journal_mode") == "wal"


def test_a_damaged_catalog_keeps_the_previous_snapshot(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    touch(library, "Indie/X/a.mp3")
    source = tmp_path / "state.sqlite"
    create_catalog(source, [(stored_path(library, "Indie/X/a.mp3"), "ok")]).close()
    out = tmp_path / "work" / "catalog-publish.sqlite"
    out.parent.mkdir()
    make_snapshot(source, library, out)
    previous = out.read_bytes()
    damage_status_index(source)

    with pytest.raises(SnapshotError, match="integrity"):
        make_snapshot(source, library, out)

    assert out.read_bytes() == previous
    assert [path.name for path in out.parent.iterdir()] == ["catalog-publish.sqlite"]
