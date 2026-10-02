import logging
import sys

import pytest

from muse_agent.proc import run_logged


def test_the_runner_logs_child_output_and_returns_its_exit_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    script = "print('first line'); print(); print('second line'); raise SystemExit(4)"

    with caplog.at_level(logging.INFO):
        code = run_logged([sys.executable, "-c", script])

    assert code == 4
    assert [message.split(": ", 1)[1] for message in caplog.messages] == [
        "first line",
        "second line",
    ]
