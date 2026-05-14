"""
Build processed/tt.db from the three processed CSV files.

Run once (or after re-processing scraped data):
    python scripts/tt_build_db.py

The resulting SQLite file is used by the Streamlit app for fast,
indexed queries over 2.6M+ matches without loading full CSVs into memory.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT      = Path(__file__).parent.parent
PROCESSED = ROOT / "processed"
DB_PATH   = PROCESSED / "tt.db"
CHUNK     = 100_000


def main():
    if DB_PATH.exists():
        print(f"Removing existing DB: {DB_PATH}")
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        _load_table(conn, PROCESSED / "matches.csv", "matches")
        _load_table(conn, PROCESSED / "sets.csv",    "sets")
        _load_table(conn, PROCESSED / "players.csv", "players")
        _create_indexes(conn)
        _print_counts(conn)
        print(f"\nDone. DB written to: {DB_PATH}")
    except Exception as exc:
        conn.close()
        DB_PATH.unlink(missing_ok=True)
        print(f"\nFailed: {exc}", file=sys.stderr)
        sys.exit(1)
    else:
        conn.close()


def _load_table(conn: sqlite3.Connection, csv_path: Path, table_name: str) -> None:
    size_mb = csv_path.stat().st_size // 1_000_000
    print(f"\nLoading {table_name} ({size_mb} MB) …")
    reader = pd.read_csv(csv_path, chunksize=CHUNK, low_memory=False)
    first  = True
    rows   = 0
    with tqdm(unit=" rows", unit_scale=True, dynamic_ncols=True) as pbar:
        for chunk in reader:
            chunk.to_sql(
                table_name,
                conn,
                if_exists="replace" if first else "append",
                index=False,
            )
            first = False
            rows += len(chunk)
            pbar.update(len(chunk))
    print(f"  → {rows:,} rows loaded")


def _create_indexes(conn: sqlite3.Connection) -> None:
    print("\nCreating indexes …")
    ddl = [
        "CREATE INDEX IF NOT EXISTS idx_m_home_slug   ON matches(home_slug)",
        "CREATE INDEX IF NOT EXISTS idx_m_away_slug   ON matches(away_slug)",
        "CREATE INDEX IF NOT EXISTS idx_m_date        ON matches(date)",
        "CREATE INDEX IF NOT EXISTS idx_m_tournament  ON matches(tournament_name)",
        "CREATE INDEX IF NOT EXISTS idx_m_status      ON matches(status_description)",
        "CREATE INDEX IF NOT EXISTS idx_m_winner      ON matches(winner)",
        "CREATE INDEX IF NOT EXISTS idx_s_event_id    ON sets(event_id)",
        "CREATE INDEX IF NOT EXISTS idx_p_slug        ON players(slug)",
        "CREATE INDEX IF NOT EXISTS idx_p_name        ON players(name)",
    ]
    for sql in ddl:
        label = sql.split("idx_")[1].split(" ON")[0]
        print(f"  {label}")
        conn.execute(sql)
    conn.commit()
    print("  Done.")


def _print_counts(conn: sqlite3.Connection) -> None:
    print()
    for table in ("matches", "sets", "players"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n:,} rows")


if __name__ == "__main__":
    main()
