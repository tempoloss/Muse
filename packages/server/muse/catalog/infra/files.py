import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from muse.catalog.domain import LibraryRoot
from muse.shared.mp3 import STREAM_KIND

REENCODE_TIMEOUT_S = 180
REENCODE = (
    "-map",
    "0:a:0",
    "-map_metadata",
    "-1",
    "-ar",
    str(STREAM_KIND.rate),
    "-ac",
    "2",
    "-c:a",
    "libmp3lame",
    "-q:a",
    "2",
    "-write_xing",
    "0",
    "-id3v2_version",
    "0",
    "-f",
    "mp3",
    "pipe:1",
)


def reencode(path: Path) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    command = [ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(path), *REENCODE]
    try:
        done = subprocess.run(command, capture_output=True, timeout=REENCODE_TIMEOUT_S, check=False)
    except OSError, subprocess.TimeoutExpired:
        return None
    return done.stdout if done.returncode == 0 and done.stdout else None


class TrackFiles:
    def __init__(
        self,
        library_dir: Path,
        root: LibraryRoot,
        encoder: Callable[[Path], bytes | None] = reencode,
    ) -> None:
        self.library_dir = library_dir
        self.root = root
        self.encoder = encoder

    def locate(self, stored: str | None) -> Path | None:
        relative = self.root.relative(stored)
        if relative is None:
            return None
        candidate = self.library_dir / relative
        if not candidate.resolve().is_relative_to(self.library_dir.resolve()):
            return None
        return candidate if candidate.is_file() else None

    def open_audio(self, stored: str | None) -> BinaryIO | None:
        path = self.locate(stored)
        if path is None:
            return None
        try:
            return path.open("rb")
        except OSError:
            return None

    def reencoded(self, stored: str | None) -> bytes | None:
        path = self.locate(stored)
        return None if path is None else self.encoder(path)
