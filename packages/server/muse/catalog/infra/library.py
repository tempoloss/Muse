from collections.abc import Iterable
from pathlib import Path


class LibraryFiles:
    def __init__(self, catalog_db: Path, playlists_dir: Path, covers_dir: Path) -> None:
        self.catalog_db = catalog_db
        self.playlists_dir = playlists_dir
        self.covers_dir = covers_dir

    def fingerprint(self) -> str:
        wal = self.catalog_db.with_name(self.catalog_db.name + "-wal")
        database = max(
            self.catalog_db.stat().st_mtime_ns, wal.stat().st_mtime_ns if wal.exists() else 0
        )
        playlists = [path.stat().st_mtime_ns for path in self.playlists_dir.glob("*.m3u8")]
        return f"{database}-{max(playlists, default=0)}-{len(playlists)}"

    def covered(self, album_ids: Iterable[int]) -> set[int]:
        return {
            album_id for album_id in album_ids if (self.covers_dir / f"{album_id}.jpg").is_file()
        }
