from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

import httpx
import structlog
from dishka import Provider, Scope, provide
from pywebpush import webpush
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from muse.identity.domain import AttemptLimiter, Users
from muse.identity.infra.ratelimit import LoginRateLimiter
from muse.identity.infra.users_file import UsersFile
from muse.notifications.domain import PushSender
from muse.notifications.infra.sender import RecordingSender, WebPushSender
from muse.notifications.infra.vapid import application_server_key
from muse.settings import Settings
from muse.shared.cache import Cache, NullCache, RedisCache
from muse.shared.clock import Clock, ZonedClock
from muse.shared.db import CatalogDb, UnitOfWork, catalog_engine, user_engine
from muse.shared.tasks import BackgroundRunner

HTTP_TIMEOUT_S = 8
USER_AGENT = "muse/1.0"

log = structlog.get_logger()


class CoreProvider(Provider):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    runner = provide(BackgroundRunner, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def limiter(self) -> AttemptLimiter:
        return LoginRateLimiter()

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return self._settings

    @provide(scope=Scope.APP)
    def users(self, settings: Settings) -> Users:
        users = UsersFile(settings.paths.users_file).load()
        for user in users.all:
            if not user.password_hash:
                log.warning(f"users: {user.id} has no password; run: muse passwd {user.id}")
        return users

    @provide(scope=Scope.APP)
    def clock(self, settings: Settings) -> Clock:
        return ZonedClock(ZoneInfo(settings.clock.timezone))

    @provide(scope=Scope.APP)
    async def catalog(self, settings: Settings) -> AsyncIterator[CatalogDb]:
        engine = catalog_engine(settings.paths.catalog_db)
        yield CatalogDb(engine)
        await engine.dispose()

    @provide(scope=Scope.APP)
    async def sessions(self, settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
        engine = user_engine(settings.paths.user_db, settings.paths.catalog_db)
        yield async_sessionmaker(engine, expire_on_commit=False)
        await engine.dispose()

    @provide(scope=Scope.APP)
    async def cache(self, settings: Settings) -> AsyncIterator[Cache]:
        if not settings.cache.redis_url:
            yield NullCache()
            return
        cache = RedisCache(settings.cache.redis_url)
        yield cache
        await cache.close()

    @provide(scope=Scope.REQUEST)
    async def unit_of_work(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> AsyncIterator[UnitOfWork]:
        async with sessions() as session:
            yield UnitOfWork(session)

    @provide(scope=Scope.APP)
    async def http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT}
        ) as client:
            yield client

    @provide(scope=Scope.APP)
    def push_sender(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        runner: BackgroundRunner,
    ) -> PushSender:
        if not settings.push.enabled:
            return RecordingSender()
        key_file = settings.paths.vapid_file
        return WebPushSender(
            public_key=application_server_key(key_file),
            key_file=key_file,
            subject=settings.push.subject,
            sessions=sessions,
            runner=runner,
            webpush=webpush,
        )
