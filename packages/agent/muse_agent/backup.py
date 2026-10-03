import json
import logging
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from muse_agent.proc import NO_WINDOW, Remote, Runner, run_logged, ssh
from muse_agent.settings import AgentConfig

DATABASE_MEMBER = "muse.sqlite"
USERS_MEMBER = "users.json"
REVISION = "SELECT version_num FROM alembic_version"

log = logging.getLogger(__name__)


class BackupError(Exception):
    pass


def backup_path(cfg: AgentConfig, day: date) -> Path:
    return cfg.paths.work_dir / "backups" / f"muse-{day.isoformat()}.tar.gz"


def pull_backup(
    cfg: AgentConfig, day: date, remote: Remote | None = None, run: Runner = run_logged
) -> Path:
    archive = backup_path(cfg, day)
    archive.parent.mkdir(parents=True, exist_ok=True)
    part = archive.with_name(f"{archive.name}.part")
    rclone = cfg.rclone
    try:
        download((remote or ssh(cfg.vps.agent_host))(f"backup {day.isoformat()}"), part)
        revision = verify(part)
        code = run([rclone.exe, "copyto", str(part), remote_file(rclone.backups_remote, archive)])
        if code != 0:
            raise BackupError(f"backup: upload failed rc={code}")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(archive)
    keep_days = cfg.schedule.backup_keep_days
    prune(archive.parent, day - timedelta(days=keep_days))
    code = run([rclone.exe, "delete", rclone.backups_remote, "--min-age", f"{keep_days}d"])
    if code != 0:
        log.warning("backup: remote prune failed rc=%d", code)
    log.info("backup: %s stored, schema %s", archive.name, revision)
    return archive


def remote_file(folder: str, archive: Path) -> str:
    separator = "" if folder.endswith((":", "/")) else "/"
    return f"{folder}{separator}{archive.name}"


def download(argv: list[str], part: Path) -> None:
    with part.open("wb") as sink:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=subprocess.PIPE,
            creationflags=NO_WINDOW,
            check=False,
        )
    if done.returncode != 0:
        reason = done.stderr.decode("utf-8", "replace").strip()
        raise BackupError(f"backup: the remote exited {done.returncode}: {reason}")


def verify(archive: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="muse-restore-") as scratch:
        restored = Path(scratch)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(restored, filter="data")
        except (tarfile.TarError, OSError, EOFError) as error:
            raise BackupError(
                f"backup: the stream is not a muse backup archive: {error}"
            ) from error
        for member in (DATABASE_MEMBER, USERS_MEMBER):
            if not (restored / member).is_file():
                raise BackupError(f"backup: the archive holds no {member}")
        try:
            json.loads((restored / USERS_MEMBER).read_text(encoding="utf-8"))
        except ValueError as error:
            raise BackupError(f"backup: {USERS_MEMBER} is not JSON: {error}") from error
        return database_revision(restored / DATABASE_MEMBER)


def database_revision(database: Path) -> str:
    try:
        with closing(sqlite3.connect(database)) as connection:
            verdict = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if verdict != "ok":
                raise BackupError(f"backup: {DATABASE_MEMBER} fails the integrity check: {verdict}")
            found = connection.execute(REVISION).fetchone()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"backup: {DATABASE_MEMBER} is unreadable: {error}") from error
    if found is None:
        raise BackupError(f"backup: {DATABASE_MEMBER} has no schema revision")
    return found[0]


def prune(folder: Path, cutoff: date) -> None:
    for archive in folder.glob("muse-*.tar.gz"):
        try:
            made = date.fromisoformat(archive.name.removeprefix("muse-").removesuffix(".tar.gz"))
        except ValueError:
            continue
        if made < cutoff:
            archive.unlink()
