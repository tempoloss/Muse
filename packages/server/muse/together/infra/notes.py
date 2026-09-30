import json
from pathlib import Path

import anyio
import structlog

from muse.together.domain import Note, note_view, valid_note

log = structlog.get_logger()


class NotesFiles:
    def __init__(self, notes_dir: Path) -> None:
        self.notes_dir = notes_dir

    async def notes(self, user_id: str) -> list[Note]:
        return await anyio.to_thread.run_sync(self.load, user_id)

    def load(self, user_id: str) -> list[Note]:
        path = self.notes_dir / f"{user_id}.json"
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8")).get("notes", [])
        except (OSError, ValueError, AttributeError) as error:
            log.warning(f"notes: {user_id}: {error}")
            return []
        if not isinstance(raw, list):
            log.warning(f'notes: {user_id}: "notes" is not a list')
            return []
        valid = [note for note in raw if valid_note(note)]
        if len(valid) != len(raw):
            log.warning(f"notes: {user_id}: skipped {len(raw) - len(valid)} invalid entries")
        return [note_view(note) for note in valid]
