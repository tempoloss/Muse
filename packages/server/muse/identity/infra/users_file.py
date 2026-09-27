import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from muse.identity.domain import InvalidUsersError, Users, parse_users


class UsersFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> object:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise InvalidUsersError(f"users.json: cannot read {self.path}: {error}") from error

    def load(self) -> Users:
        return parse_users(self._read())

    def save_hash(self, user_id: str, password_hash: str) -> None:
        data = self._read()
        entries = data.get("users") if isinstance(data, dict) else None
        entry = next(
            (e for e in entries or [] if isinstance(e, dict) and e.get("id") == user_id), None
        )
        if entry is None:
            raise InvalidUsersError(f"no such user: {user_id}")
        entry["password_hash"] = password_hash
        original = self.path.stat()
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.chmod(temporary, stat.S_IMODE(original.st_mode))
        if sys.platform != "win32":
            os.chown(temporary, original.st_uid, original.st_gid)
        os.replace(temporary, self.path)
