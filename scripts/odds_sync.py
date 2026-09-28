"""Archive timestamped table-tennis odds from Odds-API.io.

Required environment: ODDS_API_IO_KEY. Optional settings:
ODDS_API_IO_URL (API base URL; defaults to https://api.odds-api.io/v3) and
ODDS_API_IO_BOOKMAKERS (comma-separated provider bookmaker names; defaults to
the bookmakers selected for the API key).
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys
from typing import Any

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import append_odds
from models.frontier_model import canonical_event_key


DEFAULT_API_URL = "https://api.odds-api.io/v3"
EVENT_BATCH_SIZE = 10
MAX_ODDS_BATCHES_PER_RUN = 95
EVENTS_PER_RUN = EVENT_BATCH_SIZE * MAX_ODDS_BATCHES_PER_RUN


def _records(payload: object, label: str) -> list[dict[str, Any]]:
    """Return records from an API array or a conventional wrapped response."""
    records = payload
    if isinstance(payload, dict):
        records = payload.get("events", payload.get("data", payload.get("bookmakers")))
    if not isinstance(records, list):
        raise ValueError(f"Odds-API.io returned an unexpected {label} response")
    return [record for record in records if isinstance(record, dict)]


def _get_json(session: requests.Session, base_url: str, path: str, params: dict[str, object]) -> object:
    response = session.get(f"{base_url}/{path.lstrip('/')}", params=params, timeout=30)
    if not response.ok:
        # Do not include the request URL in errors: it contains the API key.
        detail = ""
        try:
            error_payload = response.json()
            if isinstance(error_payload, dict):
                detail = str(error_payload.get("error") or error_payload.get("message") or "")
        except ValueError:
            pass
        detail = detail.replace(str(params.get("apiKey", "")), "[redacted]")
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Odds-API.io {path} request failed with HTTP {response.status_code}{suffix}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Odds-API.io {path} returned invalid JSON") from exc


def _selected_bookmakers(payload: object) -> list[str]:
    if isinstance(payload, dict):
        for key in ("selectedBookmakers", "selected", "bookmakers", "data"):
            if key in payload:
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []

    names: list[str] = []
    for bookmaker in payload:
        name = (bookmaker.get("name") or bookmaker.get("bookmaker")) if isinstance(bookmaker, dict) else bookmaker
        if name:
            value = str(name).strip()
            if value and value not in names:
                names.append(value)
    return names


def _as_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _american_odds(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1:
        return None
    if decimal_odds >= 2:
        return round((decimal_odds - 1) * 100, 2)
    return round(-100 / (decimal_odds - 1), 2)


def _event_key(event: dict[str, Any]) -> tuple[str, str, str]:
    provider_event_id = str(event.get("id") or event.get("event_id") or "")
    home_name = str(event.get("home") or event.get("home_team") or event.get("homeTeam") or "")
    away_name = str(event.get("away") or event.get("away_team") or event.get("awayTeam") or "")
    start_time = str(
        event.get("date")
        or event.get("commence_time")
        or event.get("start_time")
        or event.get("startTimestamp")
        or ""
    )
    league = event.get("league")
    if isinstance(league, dict):
        league = league.get("name", "")
    key = (
        canonical_event_key(start_time, home_name, away_name, str(league or ""))
        if home_name and away_name and start_time
        else f"oddsapi:{provider_event_id}"
    )
    return key, home_name, away_name


def _append_row(
    rows: list[dict[str, object]],
    event_key: str,
    observed_at: str,
    bookmaker: str,
    market: str,
    selection: str,
    line: object,
    decimal_odds: float | None,
    american_odds: float | None,
    raw: object,
) -> None:
    if not selection or (decimal_odds is None and american_odds is None):
        return
    raw_id = f"{event_key}|{observed_at}|{bookmaker}|{market}|{selection}|{line}"
    rows.append(
        {
            "snapshot_id": "odd_" + sha256(raw_id.encode("utf-8")).hexdigest()[:24],
            "event_key": event_key,
            "observed_at": observed_at,
            "bookmaker": bookmaker,
            "market": market,
            "selection": selection,
            "line": _as_float(line),
            "american_odds": american_odds,
            "decimal_odds": decimal_odds,
            "source": "odds-api.io",
            "raw": raw,
        }
    )


def _market_rows(
    rows: list[dict[str, object]],
    event_key: str,
    home_name: str,
    away_name: str,
    observed_at: str,
    bookmaker: str,
    market: dict[str, Any],
) -> None:
    market_name = str(market.get("name") or market.get("key") or market.get("market") or "unknown")
    quotes = market.get("odds") or market.get("outcomes") or market.get("selections") or []
    if isinstance(quotes, dict):
        quotes = [quotes]
    if not isinstance(quotes, list):
        return

    aliases = {
        "home": home_name or "home",
        "away": away_name or "away",
        "draw": "draw",
        "over": "over",
        "under": "under",
        "yes": "yes",
        "no": "no",
        "odd": "odd",
        "even": "even",
        "1x": "1X",
        "12": "12",
        "x2": "X2",
    }
    price_fields = set(aliases)
    ignored_fields = {
        "hdp", "max", "line", "point", "label", "name", "selection", "description",
        "link", "homelink", "awaylink", "drawlink", "updatedat", "updated_at",
    }

    for quote in quotes:
        if not isinstance(quote, dict):
            continue

        # Keep compatibility with the older normalized payload shape.
        legacy_selection = quote.get("name") or quote.get("selection")
        legacy_decimal = _as_float(quote.get("decimal") or quote.get("price"))
        legacy_american = _as_float(quote.get("american") or quote.get("price_american"))
        if legacy_selection:
            _append_row(
                rows, event_key, observed_at, bookmaker, market_name, str(legacy_selection),
                quote.get("line") or quote.get("point") or market.get("line"),
                legacy_decimal, legacy_american, quote,
            )
            continue

        line = quote.get("hdp", quote.get("max", quote.get("line", quote.get("point"))))
        label = quote.get("label")
        labeled_price = _as_float(quote.get("odds"))
        if label and labeled_price is not None:
            _append_row(
                rows, event_key, observed_at, bookmaker, market_name, str(label), line,
                labeled_price, _american_odds(labeled_price), quote,
            )

        for field, raw_price in quote.items():
            field_key = str(field).casefold()
            if field_key not in price_fields or field_key in ignored_fields:
                continue
            decimal_odds = _as_float(raw_price)
            if decimal_odds is None:
                continue
            _append_row(
                rows, event_key, observed_at, bookmaker, market_name, aliases[field_key], line,
                decimal_odds, _american_odds(decimal_odds), quote,
            )


def normalize(payload: object, observed_at: str) -> list[dict[str, object]]:
    """Normalize Odds-API.io event odds into append_odds rows."""
    events = _records(payload, "odds")
    rows: list[dict[str, object]] = []
    for event in events:
        event_key, home_name, away_name = _event_key(event)
        bookmakers = event.get("bookmakers") or event.get("odds") or []

        # Odds-API.io's current shape maps bookmaker names to market arrays.
        if isinstance(bookmakers, dict):
            bookmaker_entries = bookmakers.items()
        elif isinstance(bookmakers, list):
            bookmaker_entries = (
                (str(book.get("name") or book.get("bookmaker") or "unknown"), book.get("markets") or [book])
                for book in bookmakers if isinstance(book, dict)
            )
        else:
            continue

        for bookmaker_name, markets in bookmaker_entries:
            if isinstance(markets, dict):
                markets = [markets]
            if not isinstance(markets, list):
                continue
            for market in markets:
                if isinstance(market, dict):
                    _market_rows(
                        rows, event_key, home_name, away_name, observed_at,
                        str(bookmaker_name), market,
                    )
    return rows


def main() -> None:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        raise SystemExit("ODDS_API_IO_KEY is not configured")

    base_url = (os.getenv("ODDS_API_IO_URL", "").strip() or DEFAULT_API_URL).rstrip("/")
    # Older deployments may set this to the former single /odds endpoint.
    if base_url.endswith("/odds"):
        base_url = base_url[: -len("/odds")]
    bookmakers_setting = os.getenv("ODDS_API_IO_BOOKMAKERS", "").strip()
    # The free API plan allows 100 requests per hour. Leave room for the
    # events and selected-bookmakers calls, and rotate pages on the four
    # six-hourly scheduled runs so later events are covered too.
    schedule_slot = datetime.now(timezone.utc).hour // 6
    event_offset = schedule_slot * EVENTS_PER_RUN
    with requests.Session() as session:
        events_payload = _get_json(
            session,
            base_url,
            "/events",
            {
                "apiKey": key,
                "sport": "table-tennis",
                "limit": EVENTS_PER_RUN,
                "skip": event_offset,
            },
        )
        events = _records(events_payload, "events")
        if not events:
            print("No upcoming table-tennis events found; no odds snapshots to archive.")
            return
        print(
            f"Fetched {len(events)} events from offset {event_offset}; "
            f"odds requests capped at {MAX_ODDS_BATCHES_PER_RUN} batches per run."
        )

        if bookmakers_setting:
            bookmakers = [name.strip() for name in bookmakers_setting.split(",") if name.strip()]
        else:
            selected_payload = _get_json(
                session,
                base_url,
                "/bookmakers/selected",
                {"apiKey": key},
            )
            bookmakers = _selected_bookmakers(selected_payload)
        if not bookmakers:
            raise RuntimeError(
                "No Odds-API.io bookmakers are selected; set ODDS_API_IO_BOOKMAKERS or select bookmakers for this API key"
            )

        event_ids = [str(event.get("id")) for event in events if event.get("id") is not None]
        observed_at = datetime.now(timezone.utc).isoformat()
        odds_events: list[dict[str, Any]] = []
        for start in range(0, len(event_ids), EVENT_BATCH_SIZE):
            batch = event_ids[start : start + EVENT_BATCH_SIZE]
            odds_payload = _get_json(
                session,
                base_url,
                "/odds/multi",
                {
                    "apiKey": key,
                    "eventIds": ",".join(batch),
                    "bookmakers": ",".join(bookmakers),
                },
            )
            odds_events.extend(_records(odds_payload, "multi-odds"))

    rows = normalize(odds_events, observed_at)
    inserted = append_odds(rows)
    print(f"Archived {inserted} new odds snapshots from {len(odds_events)} events")


if __name__ == "__main__":
    main()
