"""Import normalized external point or odds feeds into the append-only store.

This provides the ingestion boundary for licensed OddsPortal/BetExplorer Apify
exports and future point-level providers without embedding scraper credentials
or site-specific circumvention in the app.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import append_odds, append_point_events


def read_rows(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("rows") or payload.get("data") or payload.get("events") or []
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("Input must be a JSON array of objects or an object containing rows/data/events")
    return payload


def odds_rows(rows: list[dict[str, object]], source: str) -> list[dict[str, object]]:
    normalized = []
    required = {"event_key", "observed_at", "bookmaker", "market", "selection"}
    for row in rows:
        missing = required - row.keys()
        if missing:
            raise ValueError(f"Odds row is missing: {sorted(missing)}")
        raw_id = "|".join(str(row.get(k, "")) for k in ("event_key", "observed_at", "bookmaker", "market", "selection", "line"))
        normalized.append(
            {
                "snapshot_id": "odd_" + sha256(raw_id.encode("utf-8")).hexdigest()[:24],
                **row,
                "source": source,
                "raw": row,
            }
        )
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["odds", "points"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--source", required=True, choices=["oddsportal", "betexplorer", "apify", "licensed-feed"])
    args = parser.parse_args()
    rows = read_rows(args.input)
    if args.kind == "odds":
        inserted = append_odds(odds_rows(rows, args.source))
    else:
        inserted = append_point_events([{**row, "source": args.source} for row in rows])
    print(f"Imported {inserted} new {args.kind} rows")


if __name__ == "__main__":
    main()
