"""Scan Python sources for deprecated Streamlit use_container_width usage."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
EXCLUDE_DIRS = {"venv", "__pycache__", ".git"}
SELF_NAME = Path(__file__).name


def python_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*.py")
        if p.name != SELF_NAME and not any(part in EXCLUDE_DIRS for part in p.parts)
    ]


def find_uses() -> dict[Path, list[int]]:
    results: dict[Path, list[int]] = {}
    for path in python_files():
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if "use_container_width" in line:
                    results.setdefault(path, []).append(lineno)
    return results


def main() -> int:
    results = find_uses()
    if not results:
        print("OK: no deprecated use_container_width usages found.")
        return 0

    print("Deprecated Streamlit use_container_width usages found:")
    for path, lines in sorted(results.items()):
        for lineno in lines:
            print(f"  {path.relative_to(ROOT)}:{lineno}")
    print(
        "\nPlease replace use_container_width with width='stretch' or width='content'."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
