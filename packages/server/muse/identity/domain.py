import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from muse.shared.errors import DomainError

REQUIRED = ("id", "login", "name", "animal", "theme", "emoji", "nick")
INCOMPLETE = f"users.json: every user needs non-empty string {', '.join(REQUIRED)}"
DAY_S = 86400
SESSION_TTL_S = 180 * DAY_S
PASSWORD_MAX_BYTES = 72
PASSWORD_MIN_CHARS = 10
UNAUTHORIZED = "unauthorized"
BAD_CREDENTIALS = "bad credentials"


class InvalidUsersError(Exception):
    pass


class TooManyAttemptsError(DomainError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("too many attempts")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class User:
    id: str
    login: str
    name: str
    animal: str
    theme: str
    emoji: str
    nick: str
    name_gen: str | None = None
    name_dat: str | None = None
    author: bool = False
    password_hash: str | None = None

    @property
    def beast(self) -> str:
        return f"{self.emoji} {self.nick}"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "animal": self.animal,
            "theme": self.theme,
            "gen": self.name_gen or self.name,
            "dat": self.name_dat or self.name,
            "author": self.author,
        }


def normalize_login(value: str) -> str:
    return value.strip().casefold()


class Users:
    def __init__(self, first: User, second: User) -> None:
        self.all = (first, second)

    def get(self, user_id: str) -> User | None:
        return next((user for user in self.all if user.id == user_id), None)

    def partner(self, user: User) -> User:
        return next(other for other in self.all if other.id != user.id)

    def partner_id(self, user_id: str) -> str:
        return next(other.id for other in self.all if other.id != user_id)

    def by_login(self, login: str) -> User | None:
        wanted = normalize_login(login)
        return next((user for user in self.all if normalize_login(user.login) == wanted), None)

    def me(self, user: User) -> dict[str, Any]:
        return {**user.public(), "partner": self.partner(user).public()}


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _user(entry: dict[str, Any]) -> User:
    if not all(isinstance(entry.get(k), str) and entry[k].strip() for k in REQUIRED):
        raise InvalidUsersError(INCOMPLETE)
    if not isinstance(entry.get("password_hash"), (str, type(None))):
        raise InvalidUsersError(
            f"users.json: {entry['id']}: password_hash must be a string or null"
        )
    return User(
        id=entry["id"],
        login=entry["login"],
        name=entry["name"],
        animal=entry["animal"],
        theme=entry["theme"],
        emoji=entry["emoji"],
        nick=entry["nick"],
        name_gen=_optional_text(entry.get("name_gen")),
        name_dat=_optional_text(entry.get("name_dat")),
        author=bool(entry.get("author")),
        password_hash=entry.get("password_hash") or None,
    )


def parse_users(data: object) -> Users:
    entries = data.get("users") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) != 2:
        raise InvalidUsersError("users.json: need exactly 2 users")
    if not all(isinstance(entry, dict) for entry in entries):
        raise InvalidUsersError(INCOMPLETE)
    first, second = (_user(entry) for entry in entries)
    if first.id == second.id:
        raise InvalidUsersError("users.json: duplicate id")
    if normalize_login(first.login) == normalize_login(second.login):
        raise InvalidUsersError("users.json: duplicate login")
    return Users(first, second)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def needs_renewal(last_seen: int | None, now: int) -> bool:
    return now - (last_seen or 0) > DAY_S


def password_problem(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_CHARS or len(password.encode()) > PASSWORD_MAX_BYTES:
        return "password must be 10+ characters and at most 72 bytes"
    return None


@dataclass(frozen=True, slots=True)
class LiveSession:
    user_id: str
    last_seen: int | None


class SessionStore(Protocol):
    async def purge_expired(self, now: int) -> None: ...

    async def create(self, digest: str, user_id: str, now: int, user_agent: str) -> None: ...

    async def find_live(self, digest: str, now: int) -> LiveSession | None: ...

    async def renew(self, digest: str, now: int) -> None: ...

    async def delete(self, digest: str) -> None: ...


class AttemptLimiter(Protocol):
    def hit(self, keys: Sequence[str]) -> float: ...

    def clear(self, keys: Sequence[str]) -> None: ...


class PasswordStore(Protocol):
    def save_hash(self, user_id: str, password_hash: str) -> None: ...
