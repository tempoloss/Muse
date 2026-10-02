import logging
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

type Runner = Callable[[Sequence[str]], int]
type Remote = Callable[[str], list[str]]

log = logging.getLogger(__name__)


def run_logged(argv: Sequence[str]) -> int:
    name = Path(argv[0]).stem
    with subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    ) as process:
        for line in process.stdout or ():
            if text := line.rstrip():
                log.info("%s: %s", name, text)
    return process.returncode


def ssh(host: str) -> Remote:
    def remote(command: str) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", host, command]

    return remote
