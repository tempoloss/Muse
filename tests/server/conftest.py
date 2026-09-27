import json
import shutil
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import bcrypt
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from muse.app import create_app
from muse.cli import upgrade_database
from muse.settings import HttpSettings, PathsSettings, PushSettings, Settings
from muse.shared.db import user_engine
from tests.server.support import ORIGIN, PASSWORDS


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


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    path = tmp_path / "state.sqlite"
    sqlite3.connect(path).close()
    return path


@pytest.fixture
def settings(
    tmp_path: Path,
    web_dir: Path,
    catalog_db: Path,
    user_db_template: Path,
    users_document: dict[str, Any],
) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    shutil.copyfile(user_db_template, data / "muse.sqlite")
    (data / "users.json").write_text(json.dumps(users_document), encoding="utf-8")
    return Settings(
        paths=PathsSettings(
            data_dir=data, library_dir=tmp_path / "lib", catalog_db=catalog_db, web_dir=web_dir
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
async def client(settings: Settings) -> AsyncIterator[AsyncTestClient]:
    async with AsyncTestClient(app=create_app(settings), base_url=ORIGIN) as client:
        yield client
