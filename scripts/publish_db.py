"""
Rebuild tt.db from the processed CSVs and publish it to the GitHub
'db-latest' release so the Streamlit app picks it up automatically.

Prerequisites:
  - processed/matches.csv, processed/sets.csv, processed/players.csv exist
  - GitHub CLI (gh) is installed and authenticated: gh auth login

Usage:
    python scripts/publish_db.py [--skip-build]

Flags:
    --skip-build   Skip rebuilding tt.db (use the existing file as-is)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT      = Path(__file__).parent.parent
DB_PATH   = ROOT / "processed" / "tt.db"
REPO      = "gmalbert/table-tennis"
RELEASE_TAG = "db-latest"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def build_db() -> None:
    print("\n── Step 1: Rebuild tt.db ────────────────────────────────────────")
    run([sys.executable, str(ROOT / "scripts" / "tt_build_db.py")])


def ensure_release_exists() -> None:
    """Create the 'db-latest' release if it doesn't already exist."""
    result = subprocess.run(
        ["gh", "release", "view", RELEASE_TAG, "--repo", REPO],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"\n── Creating release '{RELEASE_TAG}' ────────────────────────────")
        run([
            "gh", "release", "create", RELEASE_TAG,
            "--repo", REPO,
            "--title", "Database (auto-updated)",
            "--notes", "Automatically published by scripts/publish_db.py",
        ])


def publish_db() -> None:
    print("\n── Step 2: Upload tt.db to GitHub Releases ──────────────────────")
    size_gb = DB_PATH.stat().st_size / 1e9
    print(f"  File: {DB_PATH}  ({size_gb:.2f} GB)")
    ensure_release_exists()
    run([
        "gh", "release", "upload", RELEASE_TAG,
        str(DB_PATH),
        "--repo", REPO,
        "--clobber",          # overwrite the existing asset
    ])
    print(f"\n✓ tt.db published to https://github.com/{REPO}/releases/tag/{RELEASE_TAG}")
    print("  The Streamlit app will pick it up within 12 hours automatically.")
    print("  To force an immediate refresh, delete processed/tt.db.stamp on the server.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-build", action="store_true", help="Skip rebuilding tt.db")
    args = parser.parse_args()

    if not args.skip_build:
        build_db()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run without --skip-build first.", file=sys.stderr)
        sys.exit(1)

    publish_db()


if __name__ == "__main__":
    main()
