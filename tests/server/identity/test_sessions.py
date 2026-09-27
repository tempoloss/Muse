import copy
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import bcrypt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from muse.identity.domain import (
    DAY_S,
    SESSION_TTL_S,
    TooManyAttemptsError,
    User,
    Users,
    parse_users,
)
from muse.identity.infra.ratelimit import LoginRateLimiter
from muse.identity.infra.sql import SqlSessions
from muse.identity.service import LoginResult, LoginService, SessionService
from muse.settings import Settings
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError
from tests.server.support import PASSWORDS, ManualClock

NOW_S = 1_800_000_000

type Sessions = async_sessionmaker[AsyncSession]


class Identity:
    def __init__(self, sessions: Sessions, users: Users, user_db: Path) -> None:
        self.sessions = sessions
        self.users = users
        self.user_db = user_db
        self.clock = ManualClock(NOW_S * 1000)
        self.limiter = LoginRateLimiter(lambda: self.clock.ms / 1000)

    async def login(self, login: str, password: str, user_agent: str = "ua") -> LoginResult:
        async with self.sessions() as session:
            uow = UnitOfWork(session)
            service = LoginService(self.users, SqlSessions(uow), self.limiter, self.clock, uow)
            return await service.login(login, password, "1.2.3.4", user_agent)

    async def authenticate(self, token: str | None) -> tuple[User, bool]:
        async with self.sessions() as session:
            uow = UnitOfWork(session)
            return await SessionService(self.users, SqlSessions(uow), self.clock, uow).authenticate(
                token
            )

    async def logout(self, token: str) -> None:
        async with self.sessions() as session:
            uow = UnitOfWork(session)
            await SessionService(self.users, SqlSessions(uow), self.clock, uow).logout(token)

    def rows(self) -> list[tuple[Any, ...]]:
        connection = sqlite3.connect(self.user_db)
        try:
            return connection.execute(
                "SELECT token_hash, user, created_at, last_seen, expires_at, ua FROM sessions"
            ).fetchall()
        finally:
            connection.close()


@pytest.fixture
def identity(sessions: Sessions, users_document: dict[str, Any], settings: Settings) -> Identity:
    return Identity(sessions, parse_users(users_document), settings.paths.user_db)


async def test_login_stores_only_the_token_digest_for_180_days(identity: Identity) -> None:
    result = await identity.login(" Alice ", PASSWORDS["alice"], "x" * 400)

    digest = hashlib.sha256(result.token.encode()).hexdigest()
    assert identity.rows() == [(digest, "alice", NOW_S, NOW_S, NOW_S + SESSION_TTL_S, "x" * 300)]
    assert result.me["partner"]["id"] == "bob"
    user, renew = await identity.authenticate(result.token)
    assert (user.id, renew) == ("alice", False)


async def test_a_session_idle_for_over_a_day_slides_forward(identity: Identity) -> None:
    token = (await identity.login("alice", PASSWORDS["alice"])).token

    identity.clock.ms += DAY_S * 1000
    assert (await identity.authenticate(token))[1] is False
    identity.clock.ms += 1000
    assert (await identity.authenticate(token))[1] is True

    later = NOW_S + DAY_S + 1
    assert identity.rows()[0][3:5] == (later, later + SESSION_TTL_S)
    assert (await identity.authenticate(token))[1] is False


async def test_expired_unknown_and_missing_tokens_are_unauthorized(identity: Identity) -> None:
    token = (await identity.login("alice", PASSWORDS["alice"])).token
    identity.clock.ms += SESSION_TTL_S * 1000

    for candidate in (token, "forged", None):
        with pytest.raises(DomainError, match="unauthorized"):
            await identity.authenticate(candidate)

    await identity.login("bob", PASSWORDS["bob"])
    assert [row[1] for row in identity.rows()] == ["bob"]


async def test_a_session_of_a_removed_user_is_deleted(
    identity: Identity, users_document: dict[str, Any]
) -> None:
    token = (await identity.login("alice", PASSWORDS["alice"])).token
    document = copy.deepcopy(users_document)
    document["users"][0]["id"] = "carol"
    identity.users = parse_users(document)

    with pytest.raises(DomainError, match="unauthorized"):
        await identity.authenticate(token)
    assert identity.rows() == []


async def test_logout_deletes_the_presented_session(identity: Identity) -> None:
    token = (await identity.login("alice", PASSWORDS["alice"])).token

    await identity.logout(token)

    assert identity.rows() == []


@pytest.mark.parametrize(
    ("login", "password"),
    [("alice", "wrong-password"), ("nobody", "test-pass-alice"), ("", "")],
)
async def test_bad_credentials_never_create_a_session(
    identity: Identity, login: str, password: str
) -> None:
    with pytest.raises(DomainError, match="bad credentials"):
        await identity.login(login, password)

    assert identity.rows() == []


async def test_passwords_longer_than_72_bytes_are_refused(
    identity: Identity, users_document: dict[str, Any]
) -> None:
    long_password = "ё" * 36
    document = copy.deepcopy(users_document)
    document["users"][0]["password_hash"] = bcrypt.hashpw(
        long_password.encode(), bcrypt.gensalt(4)
    ).decode()
    identity.users = parse_users(document)

    with pytest.raises(DomainError, match="bad credentials"):
        await identity.login("alice", long_password + "x")
    assert (await identity.login("alice", long_password)).me["id"] == "alice"


async def test_failures_are_limited_and_a_success_clears_the_count(identity: Identity) -> None:
    for _ in range(4):
        with pytest.raises(DomainError):
            await identity.login("alice", "wrong-password")
    await identity.login("alice", PASSWORDS["alice"])
    for _ in range(5):
        with pytest.raises(DomainError, match="bad credentials"):
            await identity.login("alice", "wrong-password")

    with pytest.raises(TooManyAttemptsError) as blocked:
        await identity.login("alice", PASSWORDS["alice"])

    assert blocked.value.retry_after == 900
