from pathlib import Path

SUFFIX = ".m3u8"


class PlaylistFiles:
    def __init__(self, playlists_dir: Path) -> None:
        self.playlists_dir = playlists_dir

    def names(self) -> list[str]:
        return sorted(path.stem for path in self.playlists_dir.glob(f"*{SUFFIX}"))

    def lines(self, name: str) -> list[str] | None:
        path = self.playlists_dir / f"{name}{SUFFIX}"
        if path.parent != self.playlists_dir or not path.is_file():
            return None
        return path.read_bytes().decode("utf-8-sig").splitlines()
