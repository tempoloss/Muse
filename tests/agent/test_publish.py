import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from muse_agent.publish import publish
from muse_agent.settings import AgentConfig
from tests.agent.support import (
    FakeRclone,
    agent_config,
    create_catalog,
    stored_path,
    stored_paths,
    touch,
)


@pytest.fixture
def cfg(tmp_path: Path) -> AgentConfig:
    cfg = agent_config(tmp_path)
    touch(cfg.paths.library_dir, "Indie/X/a.mp3")
    row = (stored_path(cfg.paths.library_dir, "indie/x/A.MP3"), "ok")
    create_catalog(cfg.paths.catalog_db, [row]).close()
    return cfg


def option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_a_failed_library_sync_publishes_no_catalog(
    cfg: AgentConfig, caplog: pytest.LogCaptureFixture
) -> None:
    rclone = FakeRclone({"sync": 7})

    with caplog.at_level(logging.INFO):
        assert publish(cfg, run=rclone) is False

    assert rclone.verbs == ["sync"]
    assert "publish: library sync failed rc=7" in caplog.messages
    assert list(cfg.paths.work_dir.iterdir()) == []


def test_the_library_is_synced_before_the_rewritten_catalog_is_uploaded(cfg: AgentConfig) -> None:
    rclone = FakeRclone()

    assert publish(cfg, run=rclone) is True

    sync, upload = rclone.calls
    assert sync[:4] == ["rclone", "sync", str(cfg.paths.library_dir), "storage:bucket/lib"]
    assert option(sync, "--transfers") == option(sync, "--checkers") == "16"
    assert option(sync, "--max-delete") == "200"
    assert upload[0:2] == ["rclone", "copyto"]
    assert upload[3] == "storage:bucket/catalog/state.sqlite"
    assert stored_paths(Path(upload[2])) == ["Indie/X/a.mp3"]


def test_an_unchanged_catalog_is_uploaded_once(cfg: AgentConfig) -> None:
    rclone = FakeRclone()

    assert publish(cfg, run=rclone) is True
    assert publish(cfg, run=rclone) is True
    assert rclone.verbs == ["sync", "copyto", "sync"]

    with closing(sqlite3.connect(cfg.paths.catalog_db)) as db:
        db.execute("INSERT INTO tracks(path, status) VALUES ('Pop/Y/b.mp3', 'ok')")
        db.commit()
    assert publish(cfg, run=rclone) is True
    assert rclone.verbs == ["sync", "copyto", "sync", "sync", "copyto"]


def test_a_failed_upload_is_retried_by_the_next_publish(cfg: AgentConfig) -> None:
    rclone = FakeRclone({"copyto": 5})

    assert publish(cfg, run=rclone) is False
    assert not (cfg.paths.work_dir / "catalog.md5").exists()

    rclone.codes.clear()
    assert publish(cfg, run=rclone) is True
    assert rclone.verbs == ["sync", "copyto", "sync", "copyto"]


def test_allowing_deletes_lifts_the_delete_cap(cfg: AgentConfig) -> None:
    rclone = FakeRclone({"sync": 1})

    publish(cfg, allow_deletes=True, run=rclone)

    assert option(rclone.calls[0], "--max-delete") == "-1"
