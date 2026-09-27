"""Run a leakage-safe time-forward replay and optionally freeze forecasts."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import DEFAULT_STORE_PATH
from models.frontier_model import FrontierElo, GlickoModel, canonical_event_key, prediction_metrics, replay_matches

DB_PATH = ROOT / "processed" / "tt.db"
REPORT_PATH = ROOT / "processed" / "frontier_backtest.json"


def load_rows(db_path: Path, warmup_start: str) -> list[dict[str, object]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT source,event_id,date,start_time_utc,tournament_name,status_description,"
            "home_name,home_slug,away_name,away_slug,winner "
            "FROM matches WHERE status_description IN ('Ended','finished') "
            "AND date>=? AND home_slug<>'' AND away_slug<>'' AND winner IN ('home','away') "
            "ORDER BY date,event_id",
            (warmup_start,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def latest_match_date(db_path: Path) -> date:
    conn = sqlite3.connect(db_path)
    try:
        value = conn.execute(
            "SELECT MAX(date) FROM matches WHERE status_description IN ('Ended','finished')"
        ).fetchone()[0]
        if not value:
            raise RuntimeError("No settled matches exist in the historical database")
        return date.fromisoformat(str(value)[:10])
    finally:
        conn.close()


def quarantine_filter(rows: list[dict[str, object]], audit_store: Path) -> tuple[list[dict[str, object]], int]:
    if not audit_store.exists():
        return rows, 0
    conn = sqlite3.connect(audit_store)
    try:
        quarantined = {
            str(row[0])
            for row in conn.execute(
                "SELECT entity_key FROM quality_flags WHERE status='open' AND severity IN ('high','critical')"
            )
        }
    finally:
        conn.close()
    kept = []
    excluded = 0
    for row in rows:
        key = canonical_event_key(
            str(row.get("start_time_utc", "")), str(row.get("home_slug", "")), str(row.get("away_slug", ""))
        )
        if key in quarantined:
            excluded += 1
        else:
            kept.append(row)
    return kept, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--days", type=int, default=365, help="Evaluation window in days")
    parser.add_argument("--warmup-days", type=int, default=730)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--audit-store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--rating-system", choices=["frontier-elo", "glicko"], default="frontier-elo")
    parser.add_argument("--compare-candidates", action="store_true")
    args = parser.parse_args()

    evaluation_start = (latest_match_date(args.db) - timedelta(days=max(30, args.days))).isoformat()
    warmup_start = (
        date.fromisoformat(evaluation_start) - timedelta(days=max(30, args.warmup_days))
    ).isoformat()
    rows = load_rows(args.db, warmup_start)
    rows, quarantined_rows = quarantine_filter(rows, args.audit_store)
    replay_model = GlickoModel() if args.rating_system == "glicko" else FrontierElo()
    predictions = replay_matches(rows, evaluation_start=evaluation_start, model=replay_model)
    metrics = prediction_metrics(predictions)
    by_tier: dict[str, dict[str, object]] = {}
    for tier in range(1, 5):
        group = [p for p in predictions if p.tournament_tier == tier]
        by_tier[str(tier)] = prediction_metrics(group)
    by_source = {
        source: prediction_metrics([p for p in predictions if p.source == source])
        for source in sorted({p.source for p in predictions})
    }
    tournament_counts: dict[str, int] = {}
    for prediction in predictions:
        tournament_counts[prediction.tournament] = tournament_counts.get(prediction.tournament, 0) + 1
    top_tournaments = sorted(tournament_counts, key=tournament_counts.get, reverse=True)[:25]
    by_tournament = {
        tournament: prediction_metrics([p for p in predictions if p.tournament == tournament])
        for tournament in top_tournaments
    }
    reliable_subset = [p for p in predictions if p.tournament_tier <= 3]

    payload = {
        "replay_schema_version": 2,
        "model_version": predictions[0].model_version if predictions else args.rating_system,
        "evaluation_start": evaluation_start,
        "warmup_start": warmup_start,
        "generated_from": args.db.name,
        "method": "event-time replay; prediction emitted before result update",
        "metrics": metrics,
        "by_tournament_tier": by_tier,
        "by_source": by_source,
        "by_top_tournament": by_tournament,
        "robustness_excluding_tier4": prediction_metrics(reliable_subset),
        "liquidity_evaluation": "unavailable until settled multi-book odds snapshots accumulate",
        "quarantined_rows_excluded": quarantined_rows,
    }
    if isinstance(replay_model, FrontierElo):
        payload["elo_leaderboard"] = [
            {
                "slug": slug,
                "elo": round(rating, 2),
                "matches": replay_model.counts.get(slug, 0),
            }
            for slug, rating in sorted(replay_model.ratings.items(), key=lambda item: item[1], reverse=True)[:250]
        ]
    if args.compare_candidates:
        from models.model_candidates import compare_candidates

        payload["candidate_comparison"] = compare_candidates(predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
