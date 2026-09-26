from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import structlog
from sqlalchemy import URL, CursorResult, event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

type Row = dict[str, Any]
type Params = Sequence[object]
type AfterCommit = Callable[[], Awaitable[None]]

BUSY_TIMEOUT_S = 30.0

log = structlog.get_logger()


def sqlite_uri(path: Path) -> str:
    return "file:" + quote(path.as_posix(), safe="/:")


def casefold(value: object) -> object:
    return value.casefold() if isinstance(value, str) else value


def register_functions(dbapi_connection: Any, _record: object = None) -> None:
    dbapi_connection.create_function("uc", 1, casefold, deterministic=True)


def _engine(database: Path, *, read_only: bool, timeout: float) -> AsyncEngine:
    query = {"uri": "true", "mode": "ro"} if read_only else {"uri": "true"}
    url = URL.create("sqlite+aiosqlite", database=sqlite_uri(database), query=query)
    return create_async_engine(url, poolclass=NullPool, connect_args={"timeout": timeout})


def catalog_engine(catalog_db: Path, timeout: float = BUSY_TIMEOUT_S) -> AsyncEngine:
    engine = _engine(catalog_db, read_only=True, timeout=timeout)
    event.listen(engine.sync_engine, "connect", register_functions)
    return engine


def user_engine(user_db: Path, catalog_db: Path, timeout: float = BUSY_TIMEOUT_S) -> AsyncEngine:
    engine = _engine(user_db, read_only=False, timeout=timeout)
    library = sqlite_uri(catalog_db) + "?mode=ro"

    def connect(dbapi_connection: Any, record: object) -> None:
        register_functions(dbapi_connection, record)
        cursor = dbapi_connection.cursor()
        cursor.execute("ATTACH DATABASE ? AS lib", (library,))
        cursor.close()

    event.listen(engine.sync_engine, "connect", connect)
    return engine


async def fetch_rows(connection: AsyncConnection, sql: str, params: Params = ()) -> list[Row]:
    result = await connection.exec_driver_sql(sql, tuple(params))
    return [dict(row) for row in result.mappings()]


async def fetch_row(connection: AsyncConnection, sql: str, params: Params = ()) -> Row | None:
    result = await connection.exec_driver_sql(sql, tuple(params))
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def fetch_value(connection: AsyncConnection, sql: str, params: Params = ()) -> Any:
    result = await connection.exec_driver_sql(sql, tuple(params))
    return result.scalar()


class CatalogDb:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def rows(self, sql: str, params: Params = ()) -> list[Row]:
        async with self.engine.connect() as connection:
            return await fetch_rows(connection, sql, params)

    async def row(self, sql: str, params: Params = ()) -> Row | None:
        async with self.engine.connect() as connection:
            return await fetch_row(connection, sql, params)

    async def value(self, sql: str, params: Params = ()) -> Any:
        async with self.engine.connect() as connection:
            return await fetch_value(connection, sql, params)


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._after_commit: list[AfterCommit] = []

    def after_commit(self, callback: AfterCommit) -> None:
        self._after_commit.append(callback)

    async def rows(self, sql: str, params: Params = ()) -> list[Row]:
        return await fetch_rows(await self.session.connection(), sql, params)

    async def row(self, sql: str, params: Params = ()) -> Row | None:
        return await fetch_row(await self.session.connection(), sql, params)

    async def value(self, sql: str, params: Params = ()) -> Any:
        return await fetch_value(await self.session.connection(), sql, params)

    async def execute(self, sql: str, params: Params = ()) -> CursorResult[Any]:
        connection = await self.session.connection()
        return await connection.exec_driver_sql(sql, tuple(params))

    async def commit(self) -> None:
        await self.session.commit()
        callbacks, self._after_commit = self._after_commit, []
        for callback in callbacks:
            try:
                await callback()
            except Exception:
                log.exception("after commit callback failed")
