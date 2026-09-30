import threading
from pathlib import Path

import anyio

from muse.diagnostics.domain import ROTATE_BYTES


class PlayerLogFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    async def append(self, line: str) -> None:
        await anyio.to_thread.run_sync(self._append, line)

    def _append(self, line: str) -> None:
        with self._lock:
            if self.path.exists() and self.path.stat().st_size > ROTATE_BYTES:
                self.path.replace(self.path.with_name(f"{self.path.name}.1"))
            with self.path.open("a", encoding="utf-8") as log:
                log.write(line)
