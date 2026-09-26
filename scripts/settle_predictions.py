"""Settle frozen paper forecasts from the latest historical result database."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import DEFAULT_STORE_PATH, append_settlements, initialize
from models.frontier_model import canonical_event_key

HISTORY_DB = ROOT / "processed" / "tt.db"


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def result_keys(minimum_date: str) -> dict[str, tuple[str, str, int]]:
    conn = sqlite3.connect(HISTORY_DB)
    try:
        rows = conn.execute(
            "SELECT start_time_utc,home_name,away_name,tournament_name,winner FROM matches "
            "WHERE status_description IN ('Ended','finished') "
            "AND winner IN ('home','away') AND event_id IS NOT NULL AND date>=? "
            "ORDER BY start_time_utc,event_id,source",
            (minimum_date,),
        )
        results: dict[str, tuple[str, str, int]] = {}
        for start_time, home_name, away_name, tournament, winner in rows:
            if not start_time:
                continue
            key = canonical_event_key(start_time, home_name, away_name, tournament)
            results.setdefault(key, (str(home_name), str(away_name), int(winner == "home")))
        return results
    finally:
        conn.close()


def main() -> None:
    initialize()
    conn = sqlite3.connect(DEFAULT_STORE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        open_predictions = conn.execute(
            "SELECT p.prediction_id,p.event_key,p.generated_at,p.event_time,p.probability_home,p.features_json "
            "FROM prediction_records p LEFT JOIN prediction_settlements s USING(prediction_id) "
            "WHERE s.prediction_id IS NULL"
        ).fetchall()
        if not open_predictions:
            print("No open frozen forecasts to settle")
            return
        minimum_date = min(str(row["event_time"])[:10] for row in open_predictions)
        results = result_keys(minimum_date)
        settlements = []
        for prediction in open_predictions:
            if prediction["event_key"] not in results:
                continue
            result_home, result_away, result_home_won = results[prediction["event_key"]]
            features = json.loads(prediction["features_json"] or "{}")
            forecast_home = _normalized_name(features.get("home"))
            if forecast_home == _normalized_name(result_home):
                actual_home = result_home_won
            elif forecast_home == _normalized_name(result_away):
                actual_home = 1 - result_home_won
            else:
                # Provider aliases have not been reconciled, so do not settle
                # a forecast against a participant orientation we cannot prove.
                continue

            favourite = _normalized_name(features.get("favourite"))
            if favourite not in {_normalized_name(result_home), _normalized_name(result_away)}:
                continue
            actual_winner = result_home if result_home_won else result_away
            forecast_won = favourite == _normalized_name(actual_winner)
            entry_decimal = features.get("entry_decimal_odds")
            entry_decimal = float(entry_decimal) if entry_decimal is not None else None
            closing_decimal = None
            if entry_decimal and entry_decimal > 1.0:
                event_time = _parse_utc(str(prediction["event_time"]))
                generated_at = _parse_utc(str(prediction["generated_at"]))
                prices = conn.execute(
                    "SELECT observed_at,selection,market,bookmaker,decimal_odds FROM odds_snapshots "
                    "WHERE event_key=? AND decimal_odds>1 "
                    "AND (?='' OR lower(bookmaker)=?) ORDER BY observed_at DESC",
                    (
                        prediction["event_key"],
                        str(features.get("entry_bookmaker") or "").casefold(),
                        str(features.get("entry_bookmaker") or "").casefold(),
                    ),
                ).fetchall()
                for observed_at, selection, market, _bookmaker, decimal_odds in prices:
                    if _normalized_name(selection) != favourite:
                        continue
                    if str(market).casefold() not in {"match_winner", "h2h", "moneyline"}:
                        continue
                    observed = _parse_utc(str(observed_at))
                    if generated_at <= observed <= event_time:
                        closing_decimal = float(decimal_odds)
                        break
            settlements.append(
                {
                    "prediction_id": prediction["prediction_id"],
                    "settled_at": datetime.now(timezone.utc).isoformat(),
                    "actual_home": actual_home,
                    "settlement_status": "settled",
                    "closing_probability": (1.0 / closing_decimal) if closing_decimal else None,
                    "paper_profit_units": (
                        entry_decimal - 1.0 if forecast_won else -1.0
                    ) if entry_decimal and entry_decimal > 1.0 else None,
                }
            )
    finally:
        conn.close()
    print(f"Settled {append_settlements(settlements)} frozen forecasts")


if __name__ == "__main__":
    main()
