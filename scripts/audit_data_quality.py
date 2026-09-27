"""Detect and quarantine recent identity, schedule, duplicate, and score anomalies."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import append_quality_flags
from models.frontier_model import canonical_event_key, participant_type

DB_PATH = ROOT / "processed" / "tt.db"


def flag(entity_key: str, code: str, severity: str, details: dict[str, object]) -> dict[str, object]:
    raw = f"{entity_key}|{code}|{details}"
    return {
        "flag_id": "flag_" + sha256(raw.encode("utf-8")).hexdigest()[:24],
        "entity_type": "match",
        "entity_key": entity_key,
        "code": code,
        "severity": severity,
        "details": details,
    }


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute("SELECT MAX(date) FROM matches").fetchone()[0]
        if not latest:
            print("No match rows available for quality audit")
            return
        cutoff = (date.fromisoformat(str(latest)[:10]) - timedelta(days=45)).isoformat()
        rows = conn.execute(
            "SELECT source,event_id,date,start_time_utc,tournament_name,status_description,home_name,home_slug,"
            "away_name,away_slug,winner,home_sets_won,away_sets_won FROM matches WHERE date>=?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    flags: list[dict[str, object]] = []
    seen: dict[str, sqlite3.Row] = {}
    schedules: Counter[tuple[str, str]] = Counter()
    score_patterns: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        event_key = canonical_event_key(
            row["start_time_utc"], row["home_slug"] or row["home_name"], row["away_slug"] or row["away_name"]
        )
        if not row["home_slug"] or not row["away_slug"]:
            flags.append(flag(event_key, "missing_identity", "high", {"source": row["source"]}))
        if row["home_slug"] and row["home_slug"] == row["away_slug"]:
            flags.append(flag(event_key, "identity_collision", "critical", {"slug": row["home_slug"]}))
        if participant_type(row["home_name"]) != participant_type(row["away_name"]):
            flags.append(flag(event_key, "mixed_participant_type", "high", {}))
        if event_key in seen:
            flags.append(
                flag(event_key, "duplicate_event", "high", {"sources": [seen[event_key]["source"], row["source"]]})
            )
        else:
            seen[event_key] = row
        for player in (row["home_slug"], row["away_slug"]):
            if player:
                schedules[(row["date"], player)] += 1
        pair = tuple(sorted((str(row["home_slug"]), str(row["away_slug"]))))
        score_patterns[pair][f"{row['home_sets_won']}-{row['away_sets_won']}"] += 1

    for (day, player), count in schedules.items():
        if count > 12:
            flags.append(flag(f"{day}:{player}", "improbable_schedule", "high", {"matches": count}))
    for pair, patterns in score_patterns.items():
        total = sum(patterns.values())
        score, count = patterns.most_common(1)[0]
        if total >= 10 and count / total >= 0.90:
            flags.append(flag("|".join(pair), "repetitive_score_pattern", "medium", {"score": score, "share": count / total}))

    print(f"Quarantined {append_quality_flags(flags)} new anomaly flags from {len(rows):,} recent rows")


if __name__ == "__main__":
    main()
