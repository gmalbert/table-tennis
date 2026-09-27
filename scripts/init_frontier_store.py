"""Create the append-only frontier audit store."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import DEFAULT_STORE_PATH, initialize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_STORE_PATH)
    args = parser.parse_args()
    print(initialize(args.path))


if __name__ == "__main__":
    main()
