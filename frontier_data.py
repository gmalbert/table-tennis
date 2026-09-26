"""Small cached-file and audit-store adapters for frontier Streamlit pages."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from models.audit_store import DEFAULT_STORE_PATH, audit_summary, ensure_local
from models.frontier_model import release_gates, source_reliability, tournament_context


ROOT = Path(__file__).parent
UPCOMING_PATH = ROOT / "processed" / "upcoming_enriched.json"
RANKINGS_PATH = ROOT / "processed" / "ittf_rankings.json"
BACKTEST_PATH = ROOT / "processed" / "frontier_backtest.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def event_key(row: dict[str, object]) -> str:
    existing = str(row.get("Event Key") or row.get("event_key") or "").strip()
    if existing:
        return existing
    raw = "|".join(
        str(row.get(key, ""))
        for key in ("_source", "_date", "Time", "Tournament", "Home", "Away")
    )
    return "evt_" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_upcoming() -> tuple[pd.DataFrame, str]:
    payload = read_json(UPCOMING_PATH, {})
    fixtures = payload.get("fixtures", []) if isinstance(payload, dict) else []
    if not fixtures:
        return pd.DataFrame(), str(payload.get("generated_at", "")) if isinstance(payload, dict) else ""
    rows: list[dict[str, object]] = []
    for item in fixtures:
        row = dict(item)
        context = tournament_context(str(row.get("Tournament", "")))
        reliability = source_reliability(str(row.get("_source", "")))
        row.setdefault("Event Key", event_key(row))
        row.setdefault("Context", context["badge"])
        row.setdefault("Tournament Tier", context["tier"])
        row.setdefault("Reliability", reliability["label"])
        row.setdefault("Reliability Score", reliability["score"])
        row.setdefault("Market Mode", "Paper-only")
        rows.append(row)
    return pd.DataFrame(rows), str(payload.get("generated_at", ""))


def load_rankings() -> tuple[pd.DataFrame, dict[str, object]]:
    payload = read_json(RANKINGS_PATH, {})
    rankings = payload.get("rankings", []) if isinstance(payload, dict) else []
    return pd.DataFrame(rankings), payload if isinstance(payload, dict) else {}


def ranking_trends() -> pd.DataFrame:
    import db

    try:
        ensure_local()
        return db.audit_ranking_trends()
    except Exception:
        return pd.DataFrame()


def load_backtest() -> dict[str, object]:
    payload = read_json(BACKTEST_PATH, {})
    try:
        replay_version = int(payload.get("replay_schema_version", 0)) if isinstance(payload, dict) else 0
    except (TypeError, ValueError):
        replay_version = 0
    if replay_version < 2:
        return {}
    return payload


def latest_odds() -> pd.DataFrame:
    import db

    try:
        ensure_local()
        return db.audit_latest_odds()
    except Exception:
        return pd.DataFrame()


def odds_movement() -> pd.DataFrame:
    import db

    try:
        ensure_local()
        return db.audit_odds_movement()
    except Exception:
        return pd.DataFrame()


def current_release_gates() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    ensure_local()
    summary = audit_summary()
    replay = load_backtest()
    overall = replay.get("metrics", {}) if isinstance(replay, dict) else {}
    robust = replay.get("robustness_excluding_tier4", {}) if isinstance(replay, dict) else {}
    robustness_passed = (
        int(replay.get("replay_schema_version", 0)) >= 2
        and int(robust.get("matches", 0)) >= 1000
        and float(robust.get("brier", 1.0)) <= float(overall.get("brier", 0.0)) + 0.01
    )
    gates = release_gates(
        frozen_forecasts=int(summary.get("frozen_forecasts", 0)),
        settled_bets=int(summary.get("settled_bets", 0)),
        positive_clv=bool(summary.get("positive_clv", False)),
        robust_low_quality_exclusion=robustness_passed,
        joint_calibration=False,
        point_level_feed=(
            int(summary.get("point_events", 0)) >= 1000
            and float(summary.get("point_latency_coverage", 0.0)) >= 0.95
        ),
    )
    return summary, gates


def feed_age_minutes(generated_at: str) -> float | None:
    if not generated_at:
        return None
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0)
    except Exception:
        return None
