import json
import logging
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from muse_agent.daily import run_daily
from muse_agent.proc import Remote
from muse_agent.settings import AgentConfig
from tests.agent.support import agent_config

DAY = date(2026, 1, 17)
PROMPT = "Ёлка 2026-01-17. Pick: 7 8 9"

REMOTE = """
import json
import sys

scenario, transcript, verb, day = sys.argv[1:5]


def say(message):
    print("MUSE:" + json.dumps(message), flush=True)


print("daily-remote: loading the library", flush=True)
if verb != "daily-remote":
    sys.exit(2)
if scenario == "exists":
    say({"state": "exists"})
    sys.exit(0)
say({"state": "prompt", "prompt": f"Ёлка {day}. Pick: 7 8 9"})
if scenario == "vanish":
    sys.exit("remote broke")
with open(transcript, "a", encoding="utf-8") as received:
    for line in sys.stdin:
        message = json.loads(line)
        received.write(json.dumps(message) + "\\n")
        received.flush()
        if message.get("done"):
            break
        print("daily-remote: checking a reply", flush=True)
        if "[7, 8, 9]" in message["reply"]:
            say({"state": "saved"})
            sys.exit(0)
        say({"state": "next"})
say({"state": "failed"})
sys.exit(1)
"""

MODEL = """
import json
import re
import sys
import time
from pathlib import Path

model, prompt_file = sys.argv[1], sys.argv[2].removeprefix("@")
prompt = Path(prompt_file).read_text(encoding="utf-8")
if model == "crash":
    sys.exit("model crashed")
if model == "sleepy":
    time.sleep(30)
if model == "silent":
    sys.exit(0)
if model == "wrong":
    print("no idea")
    sys.exit(0)
picks = re.search("Pick: ([0-9 ]+)", prompt).group(1).split()
print(json.dumps({"playlists": [int(pick) for pick in picks]}))
"""


class FakeRemote:
    def __init__(self, root: Path) -> None:
        self.script = root / "remote.py"
        self.script.write_text(REMOTE, encoding="utf-8")
        self.transcript = root / "transcript.jsonl"

    def scenario(self, name: str) -> Remote:
        def argv(command: str) -> list[str]:
            return [sys.executable, str(self.script), name, str(self.transcript), *command.split()]

        return argv

    def received(self) -> list[dict[str, object]]:
        if not self.transcript.exists():
            return []
        lines = self.transcript.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]


@pytest.fixture
def remote(tmp_path: Path) -> FakeRemote:
    return FakeRemote(tmp_path)


def with_models(tmp_path: Path, *models: str, timeout_s: int = 60) -> AgentConfig:
    cfg = agent_config(tmp_path)
    script = tmp_path / "model.py"
    script.write_text(MODEL, encoding="utf-8")
    command = (sys.executable, str(script), "{model}", "@{prompt_file}")
    daily = replace(cfg.daily, command=command, models=models, timeout_s=timeout_s)
    return replace(cfg, daily=daily)


def test_a_day_already_made_is_reported_as_existing(tmp_path: Path, remote: FakeRemote) -> None:
    cfg = with_models(tmp_path, "right")

    assert run_daily(cfg, DAY, remote=remote.scenario("exists")) == "exists"

    assert remote.received() == []
    assert not (cfg.paths.work_dir / "prompt.md").exists()


def test_a_rejected_reply_hands_the_prompt_to_the_next_model(
    tmp_path: Path, remote: FakeRemote, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = with_models(tmp_path, "wrong", "right")

    with caplog.at_level(logging.INFO):
        assert run_daily(cfg, DAY, remote=remote.scenario("prompt")) == "saved"

    assert [message["model"] for message in remote.received()] == ["wrong", "right"]
    assert (cfg.paths.work_dir / "prompt.md").read_text(encoding="utf-8") == PROMPT
    assert "daily: 2026-01-17 saved" in caplog.messages


def test_when_no_model_answers_the_remote_is_told_it_is_done(
    tmp_path: Path, remote: FakeRemote, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = with_models(tmp_path, "crash", "silent", "sleepy", "wrong", timeout_s=1)

    with caplog.at_level(logging.INFO):
        assert run_daily(cfg, DAY, remote=remote.scenario("prompt")) == "failed"

    assert remote.received() == [{"model": "wrong", "reply": "no idea\n"}, {"done": True}]
    problems = [message for message in caplog.messages if message.startswith("daily: ")]
    assert problems[0] == "daily: crash: exit 1 model crashed"
    assert problems[1] == "daily: silent: empty reply"
    assert problems[2].startswith("daily: sleepy: ")
    assert "timed out" in problems[2]
    assert problems[3:] == ["daily: 2026-01-17 failed"]


def test_a_remote_that_ends_without_a_result_counts_as_failed(
    tmp_path: Path, remote: FakeRemote, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = with_models(tmp_path, "right")

    with caplog.at_level(logging.INFO):
        assert run_daily(cfg, DAY, remote=remote.scenario("vanish")) == "failed"

    assert "remote broke" in caplog.text
    assert "daily: 2026-01-17 failed" in caplog.messages
