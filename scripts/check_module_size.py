import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMITS = (("packages", 400), ("tests", 600))


def problems(root: Path) -> list[str]:
    found = []
    for top, limit in LIMITS:
        for path in sorted((root / top).rglob("*.py")):
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > limit:
                where = path.relative_to(root).as_posix()
                found.append(f"{where}:{limit + 1}: {count} lines, limit {limit}")
    return found


def main() -> int:
    found = problems(ROOT)
    for problem in found:
        print(problem)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
