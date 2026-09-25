import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYERS_CONTRACT = "c3"
PUBLIC_MODULES = ("service", "domain")


def contexts(root: Path) -> list[str]:
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    layers = next(c for c in contracts if c["id"] == LAYERS_CONTRACT)
    return [container.removeprefix("muse.") for container in layers["containers"]]


def targets(node: ast.AST, packages: list[str]) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
        return []
    parts = node.module.split(".")
    if len(parts) == 1 or (len(parts) == 2 and parts[1] in packages):
        return [f"{node.module}.{alias.name}" for alias in node.names]
    return [node.module]


def offence(context: str, target: str) -> str | None:
    parts = target.split(".")
    if parts[0] != "muse" or len(parts) < 2 or parts[1] in (context, "shared"):
        return None
    if len(parts) == 3 and parts[2] in PUBLIC_MODULES:
        return None
    other = parts[1]
    return f"{context} imports {target}; only muse.{other}.service or muse.{other}.domain"


def problems(root: Path) -> list[str]:
    found = []
    package = root / "packages" / "server" / "muse"
    names = contexts(root)
    for context in names:
        for path in sorted((package / context).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for target in targets(node, names):
                    if message := offence(context, target):
                        line = getattr(node, "lineno", 1)
                        found.append(f"{path.relative_to(root).as_posix()}:{line}: {message}")
    return found


def main() -> int:
    found = problems(ROOT)
    for problem in found:
        print(problem)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
