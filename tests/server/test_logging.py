import json

import pytest
import structlog

from muse.shared.logging import configure_logging


def test_log_lines_are_json_objects_with_readable_unicode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    try:
        structlog.get_logger().warning("users: alice has no password", name="Алиса")
        line = capsys.readouterr().out.strip().splitlines()[-1]
    finally:
        structlog.reset_defaults()

    record = json.loads(line)
    assert (record["event"], record["level"], record["name"]) == (
        "users: alice has no password",
        "warning",
        "Алиса",
    )
    assert record["timestamp"].endswith("Z")
    assert "Алиса" in line
