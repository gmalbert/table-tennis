"""Archive timestamped table-tennis odds from odds-api.io.

Required environment: ODDS_API_IO_KEY.  The endpoint can be overridden with
ODDS_API_IO_URL so API-version changes do not require code changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import append_odds
from models.frontier_model import canonical_event_key


def normalize(payload: object, observed_at: str) -> list[dict[str, object]]:
    events = payload.get("events", payload.get("data", [])) if isinstance(payload, dict) else payload
    rows: list[dict[str, object]] = []
    if not isinstance(events, list):
        return rows
    for event in events:
        if not isinstance(event, dict):
            continue
        provider_event_id = str(event.get("id") or event.get("event_id") or "")
        home_name = str(event.get("home") or event.get("home_team") or event.get("homeTeam") or "")
        away_name = str(event.get("away") or event.get("away_team") or event.get("awayTeam") or "")
        start_time = str(event.get("commence_time") or event.get("start_time") or event.get("startTimestamp") or "")
        event_key = (
            canonical_event_key(start_time, home_name, away_name, str(event.get("tournament", "")))
            if home_name and away_name and start_time
            else f"oddsapi:{provider_event_id}"
        )
        bookmakers = event.get("bookmakers") or event.get("odds") or []
        if isinstance(bookmakers, dict):
            bookmakers = [bookmakers]
        for book in bookmakers:
            if not isinstance(book, dict):
                continue
            book_name = str(book.get("name") or book.get("bookmaker") or "unknown")
            markets = book.get("markets") or [book]
            for market in markets:
                if not isinstance(market, dict):
                    continue
                market_name = str(market.get("key") or market.get("market") or "match_winner")
                outcomes = market.get("outcomes") or market.get("selections") or []
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    selection = str(outcome.get("name") or outcome.get("selection") or "")
                    if not event_key or not selection:
                        continue
                    raw_id = f"{event_key}|{observed_at}|{book_name}|{market_name}|{selection}|{outcome.get('line')}"
                    rows.append(
                        {
                            "snapshot_id": "odd_" + sha256(raw_id.encode("utf-8")).hexdigest()[:24],
                            "event_key": event_key,
                            "observed_at": observed_at,
                            "bookmaker": book_name,
                            "market": market_name,
                            "selection": selection,
                            "line": outcome.get("line") or outcome.get("point"),
                            "american_odds": outcome.get("american") or outcome.get("price_american"),
                            "decimal_odds": outcome.get("decimal") or outcome.get("price"),
                            "source": "odds-api.io",
                            "raw": outcome,
                        }
                    )
    return rows


def main() -> None:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        raise SystemExit("ODDS_API_IO_KEY is not configured")
    url = os.getenv("ODDS_API_IO_URL", "").strip() or "https://api.odds-api.io/v3/odds"
    response = requests.get(
        url,
        params={"sport": "table-tennis"},
        headers={"Authorization": f"Bearer {key}", "X-API-Key": key},
        timeout=30,
    )
    response.raise_for_status()
    observed_at = datetime.now(timezone.utc).isoformat()
    rows = normalize(response.json(), observed_at)
    print(f"Archived {append_odds(rows)} new odds snapshots")


if __name__ == "__main__":
    main()
