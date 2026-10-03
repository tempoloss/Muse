import sqlite3
import sys
import tarfile
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from muse_agent.backup import BackupError, pull_backup
from muse_agent.main import agent_jobs
from muse_agent.proc import Remote
from muse_agent.settings import AgentConfig
from tests.agent.support import FakeRclone, agent_config

DAY = date(2026, 10, 3)
VALID = ("muse.sqlite", "users.json")

STREAM = """
import sys
from pathlib import Path

payload, code, verb = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.stdout.buffer.write(Path(payload).read_bytes())
sys.stdout.flush()
if verb != "backup 2026-10-03":
    sys.exit("denied")
if code:
    sys.exit("no backup yet")
"""


@pytest.fixture
def cfg(tmp_path: Path) -> AgentConfig:
    return agent_config(tmp_path)


def streaming(root: Path, payload: Path, code: int = 0) -> Remote:
    script = root / "stream.py"
    script.write_text(STREAM, encoding="utf-8")

    def argv(command: str) -> list[str]:
        return [sys.executable, str(script), str(payload), str(code), command]

    return argv


def user_database(path: Path, damage: str | None) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        if damage != "unversioned":
            db.execute("INSERT INTO alembic_version VALUES ('0001')")
        db.execute("CREATE TABLE likes (user TEXT, track_id INT)")
        db.execute("CREATE INDEX likes_user ON likes(user)")
        db.executemany("INSERT INTO likes VALUES (?, ?)", [(f"u{n}", n) for n in range(50)])
        if damage == "corrupt index":
            db.execute("PRAGMA writable_schema=ON")
            db.execute(
                "UPDATE sqlite_master SET sql='CREATE INDEX likes_user ON likes(track_id)' "
                "WHERE name='likes_user'"
            )
        db.commit()


def member(path: Path, damage: str | None) -> None:
    if path.name == "users.json":
        path.write_text("{" if damage == "users" else '{"users": []}', encoding="utf-8")
    elif path.name == "muse.sqlite" and damage == "garbage":
        path.write_bytes(b"not a database")
    elif path.name == "muse.sqlite":
        user_database(path, damage)
    else:
        path.write_bytes(b"data")


def archive(root: Path, *members: str, damage: str | None = None) -> Path:
    folder = root / "snapshot"
    folder.mkdir()
    path = root / "payload.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name in members:
            member(folder / name, damage)
            tar.add(folder / name, arcname=f"./{name}")
    return path


def test_a_pulled_backup_is_uploaded_and_old_copies_are_pruned(
    tmp_path: Path, cfg: AgentConfig
) -> None:
    backups = cfg.paths.work_dir / "backups"
    backups.mkdir()
    for name in ("muse-2026-09-02.tar.gz", "muse-2026-09-03.tar.gz", "muse-notes.tar.gz"):
        (backups / name).write_bytes(b"old")
    payload = archive(tmp_path, *VALID, "vapid.pem")
    rclone = FakeRclone()

    stored = pull_backup(cfg, DAY, remote=streaming(tmp_path, payload), run=rclone)

    assert stored == backups / "muse-2026-10-03.tar.gz"
    assert stored.read_bytes() == payload.read_bytes()
    assert sorted(path.name for path in backups.iterdir()) == [
        "muse-2026-09-03.tar.gz",
        "muse-2026-10-03.tar.gz",
        "muse-notes.tar.gz",
    ]
    assert rclone.calls == [
        ["rclone", "copyto", f"{stored}.part", "storage:bucket/backups/muse-2026-10-03.tar.gz"],
        ["rclone", "delete", "storage:bucket/backups", "--min-age", "30d"],
    ]


@pytest.mark.parametrize(
    ("members", "damage", "complaint"),
    [
        ((), None, "not a muse backup archive"),
        (("users.json",), None, "holds no muse.sqlite"),
        (("muse.sqlite",), None, "holds no users.json"),
        (VALID, "users", "users.json is not JSON"),
        (VALID, "garbage", "muse.sqlite is unreadable"),
        (VALID, "corrupt index", "muse.sqlite fails the integrity check"),
        (VALID, "unversioned", "muse.sqlite has no schema revision"),
    ],
)
def test_a_backup_that_would_not_restore_leaves_no_file(
    tmp_path: Path,
    cfg: AgentConfig,
    members: tuple[str, ...],
    damage: str | None,
    complaint: str,
) -> None:
    if members:
        payload = archive(tmp_path, *members, damage=damage)
    else:
        payload = tmp_path / "junk"
        payload.write_bytes(b"this is not a tarball")
    rclone = FakeRclone()

    with pytest.raises(BackupError, match=complaint):
        pull_backup(cfg, DAY, remote=streaming(tmp_path, payload), run=rclone)

    assert list((cfg.paths.work_dir / "backups").iterdir()) == []
    assert rclone.calls == []


def test_a_failing_remote_leaves_no_file(tmp_path: Path, cfg: AgentConfig) -> None:
    payload = archive(tmp_path, *VALID)
    rclone = FakeRclone()

    with pytest.raises(BackupError, match="no backup yet"):
        pull_backup(cfg, DAY, remote=streaming(tmp_path, payload, code=1), run=rclone)

    assert list((cfg.paths.work_dir / "backups").iterdir()) == []
    assert rclone.calls == []


def test_a_failed_upload_leaves_the_day_open_for_the_next_tick(
    tmp_path: Path, cfg: AgentConfig
) -> None:
    remote = streaming(tmp_path, archive(tmp_path, *VALID))
    has_backup = agent_jobs(cfg).has_backup

    with pytest.raises(BackupError, match="upload failed rc=3"):
        pull_backup(cfg, DAY, remote=remote, run=lambda _: 3)

    assert not has_backup(DAY)
    assert list((cfg.paths.work_dir / "backups").iterdir()) == []

    pull_backup(cfg, DAY, remote=remote, run=FakeRclone())

    assert has_backup(DAY)
