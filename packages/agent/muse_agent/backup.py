import logging
import subprocess
import tarfile
from datetime import date, timedelta
from pathlib import Path

from muse_agent.proc import NO_WINDOW, Remote, Runner, run_logged, ssh
from muse_agent.settings import AgentConfig

DATABASE_MEMBER = "muse.sqlite"

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
    try:
        download((remote or ssh(cfg.vps.agent_host))("backup"), part)
        verify(part)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(archive)
    rclone = cfg.rclone
    code = run([rclone.exe, "copy", str(archive), rclone.backups_remote])
    if code != 0:
        raise BackupError(f"backup: upload failed rc={code}")
    keep_days = cfg.schedule.backup_keep_days
    prune(archive.parent, day - timedelta(days=keep_days))
    code = run([rclone.exe, "delete", rclone.backups_remote, "--min-age", f"{keep_days}d"])
    if code != 0:
        log.warning("backup: remote prune failed rc=%d", code)
    log.info("backup: %s stored", archive.name)
    return archive


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


def verify(archive: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = {member.name.removeprefix("./") for member in tar if member.isfile()}
    except (tarfile.TarError, OSError, EOFError) as error:
        raise BackupError(f"backup: the stream is not a muse backup archive: {error}") from error
    if DATABASE_MEMBER not in names:
        raise BackupError(f"backup: the archive holds no {DATABASE_MEMBER}")


def prune(folder: Path, cutoff: date) -> None:
    for archive in folder.glob("muse-*.tar.gz"):
        try:
            made = date.fromisoformat(archive.name.removeprefix("muse-").removesuffix(".tar.gz"))
        except ValueError:
            continue
        if made < cutoff:
            archive.unlink()
