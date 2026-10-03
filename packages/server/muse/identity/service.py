import math
import secrets
from dataclasses import dataclass
from functools import cache

import anyio
import bcrypt

from muse.identity.domain import (
    BAD_CREDENTIALS,
    PASSWORD_MAX_BYTES,
    UNAUTHORIZED,
    AttemptLimiter,
    Me,
    PasswordStore,
    SessionStore,
    TooManyAttemptsError,
    User,
    Users,
    needs_renewal,
    new_token,
    normalize_login,
    password_problem,
    token_hash,
)
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError

BCRYPT_COST = 12
USER_AGENT_LIMIT = 300


@cache
def dummy_hash() -> bytes:
    return bcrypt.hashpw(b"muse-dummy-password", bcrypt.gensalt(BCRYPT_COST))


def password_matches(password: bytes, stored: bytes) -> bool:
    return bcrypt.checkpw(password[:PASSWORD_MAX_BYTES], stored)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_COST)).decode()


@dataclass(frozen=True, slots=True)
class LoginResult:
    me: Me
    token: str


class LoginService:
    def __init__(
        self,
        users: Users,
        sessions: SessionStore,
        limiter: AttemptLimiter,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.limiter = limiter
        self.clock = clock
        self.uow = uow

    async def login(self, login: str, password: str, client: str, user_agent: str) -> LoginResult:
        keys = (f"ip:{client}", f"login:{normalize_login(login)}")
        wait = self.limiter.hit(keys)
        if wait:
            raise TooManyAttemptsError(max(1, math.ceil(wait)))
        user = self.users.by_login(login)
        stored = user.password_hash if user else None
        secret = password.encode()
        reference = stored.encode() if stored else await anyio.to_thread.run_sync(dummy_hash)
        matched = await anyio.to_thread.run_sync(password_matches, secret, reference)
        if user is None or not (matched and stored and len(secret) <= PASSWORD_MAX_BYTES):
            raise DomainError(BAD_CREDENTIALS)
        self.limiter.clear(keys)
        token = new_token()
        now = self.clock.now_ms() // 1000
        await self.sessions.purge_expired(now)
        await self.sessions.create(token_hash(token), user.id, now, user_agent[:USER_AGENT_LIMIT])
        await self.uow.commit()
        return LoginResult(self.users.me(user), token)


class SessionService:
    def __init__(self, users: Users, sessions: SessionStore, clock: Clock, uow: UnitOfWork) -> None:
        self.users = users
        self.sessions = sessions
        self.clock = clock
        self.uow = uow

    async def authenticate(self, token: str | None) -> tuple[User, bool]:
        if not token:
            raise DomainError(UNAUTHORIZED)
        digest, now = token_hash(token), self.clock.now_ms() // 1000
        live = await self.sessions.find_live(digest, now)
        if live is None:
            raise DomainError(UNAUTHORIZED)
        user = self.users.get(live.user_id)
        if user is None:
            await self.sessions.delete(digest)
            await self.uow.commit()
            raise DomainError(UNAUTHORIZED)
        renew = needs_renewal(live.last_seen, now)
        if renew:
            await self.sessions.renew(digest, now)
            await self.uow.commit()
        return user, renew

    async def logout(self, token: str) -> None:
        await self.sessions.delete(token_hash(token))
        await self.uow.commit()


class PasswordService:
    def __init__(self, store: PasswordStore) -> None:
        self.store = store

    def set(self, user_id: str, password: str) -> None:
        if problem := password_problem(password):
            raise DomainError(problem)
        self.store.save_hash(user_id, hash_password(password))

    def set_random(self, user_id: str) -> str:
        password = secrets.token_urlsafe(12)
        self.store.save_hash(user_id, hash_password(password))
        return password
