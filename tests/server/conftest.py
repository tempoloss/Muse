import json
import shutil
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import bcrypt
import httpx
import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from muse.app import create_app
from muse.notifications.domain import PushSender
from muse.notifications.infra.sender import RecordingSender
from muse.settings import HttpSettings, PathsSettings, PushSettings, Settings
from muse.shared.db import user_engine
from muse.userdb import upgrade_database
from tests.fixtures.catalog import FixtureCatalog, build_catalog
from tests.server.support import ORIGIN, PASSWORDS, browser, signed_in


def playable_ids(library: FixtureCatalog, count: int) -> list[int]:
    uri = f"file:{library.catalog_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute(
            "SELECT id FROM tracks WHERE status='ok' AND dur>60 ORDER BY id LIMIT ?", (count,)
        ).fetchall()
    return [row[0] for row in rows]


@pytest.fixture(scope="session")
def user_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template") / "muse.sqlite"
    upgrade_database(path)
    return path


@pytest.fixture(scope="session")
def users_document() -> dict[str, Any]:
    hashes = {
        uid: bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()
        for uid, password in PASSWORDS.items()
    }
    return {
        "users": [
            {
                "id": "alice",
                "login": "alice",
                "name": "Алиса",
                "animal": "fox",
                "theme": "light",
                "emoji": "🦊",
                "nick": "Лисёнок",
                "password_hash": hashes["alice"],
            },
            {
                "id": "bob",
                "login": "Bob",
                "name": "Боб",
                "name_gen": "Боба",
                "name_dat": "Бобу",
                "author": True,
                "animal": "bear",
                "theme": "dark",
                "emoji": "🐻",
                "nick": "Мишка",
                "password_hash": hashes["bob"],
            },
        ]
    }


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<p>shell</p>", encoding="utf-8")
    (web / "assets" / "a.js").write_text("1", encoding="utf-8")
    (web / "sw.js").write_text("self", encoding="utf-8")
    return web


@pytest.fixture(scope="session")
def library(tmp_path_factory: pytest.TempPathFactory) -> FixtureCatalog:
    return build_catalog(tmp_path_factory.mktemp("catalog"))


@pytest.fixture
def track_id(library: FixtureCatalog) -> int:
    return playable_ids(library, 1)[0]


@pytest.fixture
def other_track_id(library: FixtureCatalog) -> int:
    return playable_ids(library, 2)[1]


@pytest.fixture
def settings(
    tmp_path: Path,
    web_dir: Path,
    library: FixtureCatalog,
    user_db_template: Path,
    users_document: dict[str, Any],
) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    shutil.copyfile(user_db_template, data / "muse.sqlite")
    (data / "users.json").write_text(json.dumps(users_document), encoding="utf-8")
    return Settings(
        paths=PathsSettings(
            data_dir=data,
            library_dir=library.library_dir,
            catalog_db=library.catalog_db,
            web_dir=web_dir,
        ),
        http=HttpSettings(public_host="music.example.org", origins=(ORIGIN,)),
        push=PushSettings(enabled=False),
    )


@pytest.fixture
async def sessions(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = user_engine(settings.paths.user_db, settings.paths.catalog_db)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Litestar]:
    application = create_app(settings)
    async with AsyncTestClient(app=application, base_url=ORIGIN):
        yield application


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[httpx.AsyncClient]:
    async with browser(app) as anonymous:
        yield anonymous


@pytest.fixture
async def alice(app: Litestar) -> AsyncIterator[httpx.AsyncClient]:
    client = await signed_in(app, "alice")
    yield client
    await client.aclose()


@pytest.fixture
async def bob(app: Litestar) -> AsyncIterator[httpx.AsyncClient]:
    client = await signed_in(app, "bob")
    yield client
    await client.aclose()


@pytest.fixture
async def pushes(app: Litestar) -> RecordingSender:
    sender = await app.state.dishka_container.get(PushSender)
    assert isinstance(sender, RecordingSender)
    return sender
