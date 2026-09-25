from pathlib import Path

from scripts import check_context_imports, check_module_size

CONTRACTS = """
[[tool.importlinter.contracts]]
id = "c3"
containers = ["muse.alpha", "muse.beta"]
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_size_limits_differ_for_packages_and_tests(tmp_path: Path) -> None:
    write(tmp_path, "packages/p/fits.py", "x = 1\n" * 400)
    write(tmp_path, "packages/p/big.py", "x = 1\n" * 401)
    write(tmp_path, "tests/test_fits.py", "x = 1\n" * 600)
    write(tmp_path, "tests/test_big.py", "x = 1\n" * 601)
    write(tmp_path, "scripts/unchecked.py", "x = 1\n" * 900)

    assert check_module_size.problems(tmp_path) == [
        "packages/p/big.py:401: 401 lines, limit 400",
        "tests/test_big.py:601: 601 lines, limit 600",
    ]


def test_contexts_reach_each_other_only_through_service_or_domain(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", CONTRACTS)
    lines = [
        "import json",
        "import muse.beta.service",
        "from muse.beta.domain import Thing",
        "from muse.beta import service, domain",
        "from muse.shared.db import UnitOfWork",
        "from muse.alpha.infra.sql import Rows",
        "from muse.beta.infra.sql import Repo",
        "from muse.beta import infra",
        "import muse.beta",
        "from muse.settings import Settings",
        "from muse.beta.service.inner import x",
    ]
    write(tmp_path, "packages/server/muse/alpha/service.py", "\n".join(lines) + "\n")
    rule = "only muse.beta.service or muse.beta.domain"

    assert check_context_imports.problems(tmp_path) == [
        f"packages/server/muse/alpha/service.py:7: alpha imports muse.beta.infra.sql; {rule}",
        f"packages/server/muse/alpha/service.py:8: alpha imports muse.beta.infra; {rule}",
        f"packages/server/muse/alpha/service.py:9: alpha imports muse.beta; {rule}",
        "packages/server/muse/alpha/service.py:10: alpha imports muse.settings; "
        "only muse.settings.service or muse.settings.domain",
        f"packages/server/muse/alpha/service.py:11: alpha imports muse.beta.service.inner; {rule}",
    ]
