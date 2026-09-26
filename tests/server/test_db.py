import os
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from muse.shared.db import CatalogDb, UnitOfWork, catalog_engine, user_engine

CATALOG = (
    "CREATE TABLE tracks(id INTEGER PRIMARY KEY, title TEXT); INSERT INTO tracks VALUES (1, '{}');"
)
USER = (
    "CREATE TABLE plays(user TEXT, track_id INT);"
    "CREATE TABLE pet(id INTEGER PRIMARY KEY, food REAL); INSERT INTO pet VALUES (1, 50);"
)


def make_db(path: Path, script: str) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(script)
    connection.close()
    return path


def count_plays(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    finally:
        connection.close()


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    return make_db(tmp_path / "state.sqlite", CATALOG.format("Ёлка"))


@pytest.fixture
def user_db(tmp_path: Path) -> Path:
    return make_db(tmp_path / "muse.sqlite", USER)


@pytest.fixture
async def sessions(user_db: Path, catalog: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = user_engine(user_db, catalog)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_the_catalog_is_read_only_and_casefolds_with_uc(catalog: Path) -> None:
    db = CatalogDb(catalog_engine(catalog))

    assert await db.value("SELECT uc('ÄB')") == "äb"
    assert await db.rows("SELECT id FROM tracks WHERE uc(title) LIKE ?", ("%ёл%",)) == [{"id": 1}]
    with pytest.raises(OperationalError, match="readonly"):
        await db.value("INSERT INTO tracks VALUES (2, 'x')")


async def test_an_atomically_replaced_catalog_is_seen_by_the_next_query(
    catalog: Path, tmp_path: Path
) -> None:
    db = CatalogDb(catalog_engine(catalog))
    assert await db.row("SELECT title FROM tracks") == {"title": "Ёлка"}

    os.replace(make_db(tmp_path / "fresh.sqlite", CATALOG.format("Новое")), catalog)

    assert await db.row("SELECT title FROM tracks") == {"title": "Новое"}


async def test_the_user_database_reads_the_library_but_cannot_write_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        uow = UnitOfWork(session)

        assert await uow.value("SELECT uc(title) FROM lib.tracks WHERE id=1") == "ёлка"
        with pytest.raises(OperationalError, match="readonly"):
            await uow.execute("DELETE FROM lib.tracks")


async def test_commit_persists_and_then_runs_callbacks_in_order(
    sessions: async_sessionmaker[AsyncSession], user_db: Path
) -> None:
    seen: list[tuple[str, int]] = []

    async def first() -> None:
        seen.append(("first", count_plays(user_db)))

    async def second() -> None:
        seen.append(("second", count_plays(user_db)))

    async with sessions() as session:
        uow = UnitOfWork(session)
        result = await uow.execute("INSERT INTO plays VALUES ('alice', 7)")
        uow.after_commit(first)
        uow.after_commit(second)
        assert (result.rowcount, seen) == (1, [])

        await uow.commit()

    assert seen == [("first", 1), ("second", 1)]


async def test_leaving_without_commit_discards_writes_and_callbacks(
    sessions: async_sessionmaker[AsyncSession], user_db: Path
) -> None:
    called: list[str] = []

    async def callback() -> None:
        called.append("callback")

    async with sessions() as session:
        uow = UnitOfWork(session)
        await uow.execute("INSERT INTO plays VALUES ('alice', 7)")
        uow.after_commit(callback)

    assert (count_plays(user_db), called) == (0, [])


async def test_a_failing_callback_is_logged_and_later_ones_still_run(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ran: list[str] = []

    async def broken() -> None:
        raise RuntimeError("push service down")

    async def healthy() -> None:
        ran.append("healthy")

    async with sessions() as session:
        uow = UnitOfWork(session)
        uow.after_commit(broken)
        uow.after_commit(healthy)
        with capture_logs() as logs:
            await uow.commit()

    assert ran == ["healthy"]
    assert [entry["event"] for entry in logs] == ["after commit callback failed"]


async def test_a_write_statement_holds_the_write_lock_until_commit(
    user_db: Path, catalog: Path
) -> None:
    holder_engine = user_engine(user_db, catalog)
    waiter_engine = user_engine(user_db, catalog, timeout=0.1)
    holders = async_sessionmaker(holder_engine)
    waiters = async_sessionmaker(waiter_engine)

    async with holders() as session:
        holder = UnitOfWork(session)
        await holder.execute("UPDATE plays SET user=user WHERE 0")
        async with waiters() as blocked:
            with pytest.raises(OperationalError, match="locked"):
                await UnitOfWork(blocked).execute("UPDATE pet SET food=food+1 WHERE id=1")
        await holder.commit()

    async with waiters() as session:
        waiter = UnitOfWork(session)
        await waiter.execute("UPDATE pet SET food=food+1 WHERE id=1")
        await waiter.commit()
        assert await waiter.value("SELECT food FROM pet") == 51
    await holder_engine.dispose()
    await waiter_engine.dispose()
