import io
import subprocess
import sys
import tarfile
from pathlib import Path

from muse_agent import settings

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = "/usr/local/bin/muse-install-release"


class DeployError(Exception):
    pass


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def owned_by_root(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.uid = member.gid = 0
    member.uname = member.gname = "root"
    member.mode = 0o755 if member.isdir() else 0o644
    return member


def build_release(root: Path, web_dist: Path) -> bytes:
    if git(root, "status", "--porcelain").strip():
        raise DeployError("the working tree has uncommitted or untracked files; commit them first")
    if not (web_dist / "index.html").is_file():
        raise DeployError(f"{web_dist} has no index.html; build the web client first")
    source = git(root, "-c", "tar.umask=0022", "archive", "--format=tar", "--prefix=src/", "HEAD")
    release = io.BytesIO(source)
    with tarfile.open(fileobj=release, mode="a") as archive:
        archive.add(web_dist, arcname="web", filter=owned_by_root)
    return release.getvalue()


def main() -> int:
    try:
        cfg = settings.load()
        release = build_release(ROOT, cfg.deploy.web_dist)
    except (settings.ConfigError, DeployError) as error:
        print(f"deploy: {error}", file=sys.stderr)
        return 1
    sha = git(ROOT, "rev-parse", "--short", "HEAD").decode("ascii").strip()
    install = ["ssh", cfg.deploy.admin_host, f"{INSTALLER} {sha}"]
    return subprocess.run(install, input=release, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
