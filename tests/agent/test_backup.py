import sys
import tarfile
from datetime import date
from pathlib import Path

import pytest

from muse_agent.backup import BackupError, pull_backup
from muse_agent.proc import Remote
from muse_agent.settings import AgentConfig
from tests.agent.support import FakeRclone, agent_config

DAY = date(2026, 10, 3)

STREAM = """
import sys
from pathlib import Path

payload, code, verb = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.stdout.buffer.write(Path(payload).read_bytes())
sys.stdout.flush()
if verb != "backup":
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


def archive(root: Path, *members: str) -> Path:
    folder = root / "snapshot"
    folder.mkdir()
    path = root / "payload.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for member in members:
            (folder / member).write_bytes(b"data")
            tar.add(folder / member, arcname=f"./{member}")
    return path


def test_a_pulled_backup_is_uploaded_and_old_copies_are_pruned(
    tmp_path: Path, cfg: AgentConfig
) -> None:
    backups = cfg.paths.work_dir / "backups"
    backups.mkdir()
    for name in ("muse-2026-09-02.tar.gz", "muse-2026-09-03.tar.gz", "muse-notes.tar.gz"):
        (backups / name).write_bytes(b"old")
    payload = archive(tmp_path, "muse.sqlite", "users.json")
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
        ["rclone", "copy", str(stored), "storage:bucket/backups"],
        ["rclone", "delete", "storage:bucket/backups", "--min-age", "30d"],
    ]


@pytest.mark.parametrize(
    ("members", "complaint"),
    [((), "not a muse backup archive"), (("users.json",), "holds no muse.sqlite")],
)
def test_a_stream_that_is_not_a_backup_leaves_no_file(
    tmp_path: Path, cfg: AgentConfig, members: tuple[str, ...], complaint: str
) -> None:
    if members:
        payload = archive(tmp_path, *members)
    else:
        payload = tmp_path / "junk"
        payload.write_bytes(b"this is not a tarball")
    rclone = FakeRclone()

    with pytest.raises(BackupError, match=complaint):
        pull_backup(cfg, DAY, remote=streaming(tmp_path, payload), run=rclone)

    assert list((cfg.paths.work_dir / "backups").iterdir()) == []
    assert rclone.calls == []


def test_a_failing_remote_leaves_no_file(tmp_path: Path, cfg: AgentConfig) -> None:
    payload = archive(tmp_path, "muse.sqlite")
    rclone = FakeRclone()

    with pytest.raises(BackupError, match="no backup yet"):
        pull_backup(cfg, DAY, remote=streaming(tmp_path, payload, code=1), run=rclone)

    assert list((cfg.paths.work_dir / "backups").iterdir()) == []
    assert rclone.calls == []
