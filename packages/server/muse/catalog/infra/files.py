from pathlib import Path

from muse.catalog.domain import LibraryRoot


class TrackFiles:
    def __init__(self, library_dir: Path, root: LibraryRoot) -> None:
        self.library_dir = library_dir
        self.root = root

    def locate(self, stored: str | None) -> Path | None:
        relative = self.root.relative(stored)
        if relative is None:
            return None
        candidate = self.library_dir / relative
        if not candidate.resolve().is_relative_to(self.library_dir.resolve()):
            return None
        return candidate if candidate.is_file() else None
