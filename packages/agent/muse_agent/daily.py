import json
import logging
import subprocess
import tempfile
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import IO, Literal

from muse_agent.proc import NO_WINDOW, Remote, ssh
from muse_agent.settings import AgentConfig

type DailyResult = Literal["saved", "exists", "failed"]

MESSAGE_PREFIX = "MUSE:"
PROMPT_NAME = "prompt.md"
REAP_WAIT_S = 10

log = logging.getLogger(__name__)


class ConversationError(Exception):
    pass


class Channel:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        assert process.stdin is not None
        self.reader = process.stdout
        self.writer = process.stdin

    def receive(self) -> dict[str, object]:
        for line in self.reader:
            if not line.startswith(MESSAGE_PREFIX):
                continue
            try:
                message = json.loads(line.removeprefix(MESSAGE_PREFIX))
            except ValueError as error:
                raise ConversationError(f"unreadable message: {error}") from error
            if not isinstance(message, dict):
                raise ConversationError("unreadable message")
            return message
        raise ConversationError("the remote ended without a result")

    def state(self) -> object:
        return self.receive().get("state")

    def send(self, message: dict[str, object]) -> None:
        try:
            self.writer.write(json.dumps(message) + "\n")
            self.writer.flush()
        except OSError as error:
            raise ConversationError("the remote stopped reading") from error


def run_daily(cfg: AgentConfig, day: date, remote: Remote | None = None) -> DailyResult:
    argv = (remote or ssh(cfg.vps.agent_host))(f"daily-remote {day.isoformat()}")
    with tempfile.TemporaryFile() as remote_errors:
        try:
            result = talk(cfg, argv, remote_errors)
        except ConversationError as error:
            log.warning("daily: %s: %s", error, last_line(remote_errors))
            result = "failed"
    log.info("daily: %s %s", day.isoformat(), result)
    return result


def talk(cfg: AgentConfig, argv: list[str], remote_errors: IO[bytes]) -> DailyResult:
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=remote_errors,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    try:
        return converse(cfg, Channel(process))
    finally:
        reap(process)


def converse(cfg: AgentConfig, channel: Channel) -> DailyResult:
    opening = channel.receive()
    state, prompt = opening.get("state"), opening.get("prompt")
    if state == "exists":
        return "exists"
    if state != "prompt" or not isinstance(prompt, str):
        return settled(state)
    prompt_file = cfg.paths.work_dir / PROMPT_NAME
    prompt_file.write_text(prompt, encoding="utf-8")
    for model in cfg.daily.models:
        reply = ask(cfg, model, prompt_file)
        if reply is None:
            continue
        channel.send({"model": model, "reply": reply})
        state = channel.state()
        if state != "next":
            return settled(state)
    channel.send({"done": True})
    return settled(channel.state())


def settled(state: object) -> DailyResult:
    return "saved" if state == "saved" else "failed"


def ask(cfg: AgentConfig, model: str, prompt_file: Path) -> str | None:
    argv = [
        part.replace("{model}", model).replace("{prompt_file}", str(prompt_file))
        for part in cfg.daily.command
    ]
    try:
        done = subprocess.run(
            argv,
            cwd=cfg.paths.work_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.daily.timeout_s,
            creationflags=NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("daily: %s: %s", model, error)
        return None
    if done.returncode != 0:
        log.warning("daily: %s: exit %d %s", model, done.returncode, done.stderr.strip()[-300:])
        return None
    if not done.stdout.strip():
        log.warning("daily: %s: empty reply", model)
        return None
    return done.stdout


def reap(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            with suppress(OSError):
                stream.close()
    try:
        process.wait(timeout=REAP_WAIT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def last_line(stream: IO[bytes]) -> str:
    stream.seek(0)
    lines = stream.read().decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else "no error output"
