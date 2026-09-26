"""Append-only SQLite store for forecasts, prices, quality flags, and corrections."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Mapping, Sequence


DEFAULT_STORE_PATH = Path(__file__).parent.parent / "processed" / "frontier_audit.db"
FRONTIER_RELEASE_URL = "https://github.com/gmalbert/table-tennis/releases/download/frontier-latest/frontier_audit.db"
SCHEMA_VERSION = 1


DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_identities (
    stable_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    participant_type TEXT NOT NULL CHECK(participant_type IN ('individual','team_or_doubles','unknown')),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_profile_snapshots (
    stable_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    birth_year INTEGER,
    handedness TEXT,
    playing_style TEXT,
    serve_quality REAL,
    receive_quality REAL,
    rally_length_avg REAL,
    attack_rate REAL,
    return_quality REAL,
    rubber_change_recent INTEGER NOT NULL DEFAULT 0,
    equipment_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL,
    PRIMARY KEY(stable_id, observed_at, source)
);
CREATE TABLE IF NOT EXISTS rankings (
    observed_at TEXT NOT NULL,
    category TEXT NOT NULL,
    rank INTEGER NOT NULL,
    stable_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    points REAL,
    source TEXT NOT NULL DEFAULT 'ittf',
    PRIMARY KEY (observed_at, category, stable_id)
);
CREATE TABLE IF NOT EXISTS odds_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    american_odds REAL,
    decimal_odds REAL,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(event_key, observed_at, bookmaker, market, selection, line)
);
CREATE TABLE IF NOT EXISTS prediction_records (
    prediction_id TEXT PRIMARY KEY,
    event_key TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    event_time TEXT NOT NULL,
    model_version TEXT NOT NULL,
    probability_home REAL NOT NULL CHECK(probability_home BETWEEN 0 AND 1),
    coverage REAL NOT NULL CHECK(coverage BETWEEN 0 AND 1),
    abstained INTEGER NOT NULL CHECK(abstained IN (0,1)),
    feature_cutoff TEXT NOT NULL,
    features_json TEXT NOT NULL,
    UNIQUE(event_key, generated_at, model_version)
);
CREATE TABLE IF NOT EXISTS prediction_settlements (
    prediction_id TEXT PRIMARY KEY REFERENCES prediction_records(prediction_id),
    settled_at TEXT NOT NULL,
    actual_home INTEGER NOT NULL CHECK(actual_home IN (0,1)),
    settlement_status TEXT NOT NULL,
    closing_probability REAL,
    paper_profit_units REAL
);
CREATE TABLE IF NOT EXISTS point_events (
    event_key TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    game_number INTEGER NOT NULL,
    home_points INTEGER NOT NULL,
    away_points INTEGER NOT NULL,
    server TEXT,
    timeout_state TEXT,
    feed_latency_ms INTEGER,
    source TEXT NOT NULL,
    PRIMARY KEY(event_key, sequence_number)
);
CREATE TABLE IF NOT EXISTS match_metadata (
    event_key TEXT PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    competition_tier INTEGER,
    tour TEXT,
    gender TEXT,
    format_best_of INTEGER,
    stage TEXT,
    venue TEXT,
    country TEXT,
    ball TEXT,
    table_model TEXT,
    floor_type TEXT,
    retirement INTEGER NOT NULL DEFAULT 0,
    walkover INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS quality_flags (
    flag_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS correction_requests (
    correction_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    requested_change TEXT NOT NULL,
    evidence_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS notification_log (
    notification_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    event_key TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_odds_event_time ON odds_snapshots(event_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_predictions_event_time ON prediction_records(event_key, event_time);
CREATE INDEX IF NOT EXISTS idx_quality_status ON quality_flags(status, severity);
"""

IMMUTABLE_TABLES = (
    "odds_snapshots",
    "prediction_records",
    "prediction_settlements",
    "point_events",
    "player_profile_snapshots",
    "match_metadata",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path: Path | str = DEFAULT_STORE_PATH) -> Iterator[sqlite3.Connection]:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path: Path | str = DEFAULT_STORE_PATH) -> Path:
    db_path = Path(path)
    with connect(db_path) as conn:
        conn.executescript(DDL)
        row = conn.execute("SELECT MAX(version) AS version FROM schema_meta").fetchone()
        if row["version"] is None:
            conn.execute("INSERT INTO schema_meta(version, applied_at) VALUES (?, ?)", (SCHEMA_VERSION, utc_now()))
        for table in IMMUTABLE_TABLES:
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS prevent_{table}_update "
                f"BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS prevent_{table}_delete "
                f"BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    return db_path


def ensure_local(path: Path | str = DEFAULT_STORE_PATH) -> Path:
    """Restore the published audit artifact once, or initialize an empty store."""
    db_path = Path(path)
    if db_path.exists():
        return initialize(db_path)
    try:
        import requests

        response = requests.get(FRONTIER_RELEASE_URL, timeout=30)
        response.raise_for_status()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = db_path.with_suffix(".download")
        temp_path.write_bytes(response.content)
        temp_path.replace(db_path)
    except Exception:
        pass
    return initialize(db_path)


def append_odds(rows: Sequence[Mapping[str, object]], path: Path | str = DEFAULT_STORE_PATH) -> int:
    initialize(path)
    inserted = 0
    sql = """INSERT OR IGNORE INTO odds_snapshots
        (snapshot_id,event_key,observed_at,bookmaker,market,selection,line,american_odds,decimal_odds,source,raw_json)
        VALUES (:snapshot_id,:event_key,:observed_at,:bookmaker,:market,:selection,:line,:american_odds,:decimal_odds,:source,:raw_json)"""
    with connect(path) as conn:
        for source_row in rows:
            row = dict(source_row)
            row.setdefault("observed_at", utc_now())
            row.setdefault("line", None)
            row.setdefault("american_odds", None)
            row.setdefault("decimal_odds", None)
            row.setdefault("source", "unknown")
            row["raw_json"] = json.dumps(row.pop("raw", {}), ensure_ascii=False, sort_keys=True)
            before = conn.total_changes
            conn.execute(sql, row)
            inserted += conn.total_changes - before
    return inserted


def append_rankings(
    rows: Sequence[Mapping[str, object]],
    observed_at: str,
    path: Path | str = DEFAULT_STORE_PATH,
) -> int:
    initialize(path)
    inserted = 0
    with connect(path) as conn:
        for source_row in rows:
            row = dict(source_row)
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO rankings(observed_at,category,rank,stable_id,player_name,country,points,source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    observed_at,
                    str(row.get("category", "unknown")),
                    int(row["rank"]),
                    str(row["stable_id"]),
                    str(row["player"]),
                    str(row.get("country", "")),
                    float(row.get("points", 0) or 0),
                    "ittf",
                ),
            )
            inserted += conn.total_changes - before
    return inserted


def append_predictions(rows: Sequence[Mapping[str, object]], path: Path | str = DEFAULT_STORE_PATH) -> int:
    initialize(path)
    inserted = 0
    sql = """INSERT OR IGNORE INTO prediction_records
        (prediction_id,event_key,generated_at,event_time,model_version,probability_home,coverage,abstained,feature_cutoff,features_json)
        VALUES (:prediction_id,:event_key,:generated_at,:event_time,:model_version,:probability_home,:coverage,:abstained,:feature_cutoff,:features_json)"""
    with connect(path) as conn:
        for source_row in rows:
            row = dict(source_row)
            row.setdefault("generated_at", utc_now())
            row.setdefault("feature_cutoff", row["generated_at"])
            generated_at = datetime.fromisoformat(str(row["generated_at"]).replace("Z", "+00:00"))
            event_time = datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00"))
            feature_cutoff = datetime.fromisoformat(str(row["feature_cutoff"]).replace("Z", "+00:00"))
            if feature_cutoff > generated_at:
                raise ValueError("feature_cutoff cannot be later than generated_at")
            if generated_at > event_time:
                raise ValueError("generated_at cannot be later than event_time")
            row["abstained"] = int(bool(row.get("abstained", False)))
            row["features_json"] = json.dumps(row.pop("features", {}), ensure_ascii=False, sort_keys=True)
            before = conn.total_changes
            conn.execute(sql, row)
            inserted += conn.total_changes - before
    return inserted


def audit_summary(path: Path | str = DEFAULT_STORE_PATH) -> dict[str, object]:
    db_path = Path(path)
    if not db_path.exists():
        return {
            "frozen_forecasts": 0,
            "settled_bets": 0,
            "positive_clv": False,
            "open_quality_flags": 0,
            "point_events": 0,
            "point_latency_coverage": 0.0,
        }
    with connect(db_path) as conn:
        forecasts = conn.execute(
            "SELECT COUNT(DISTINCT event_key) FROM prediction_records "
            "WHERE json_extract(features_json,'$.replay') IS NULL"
        ).fetchone()[0]
        settled = conn.execute(
            "SELECT COUNT(DISTINCT p.event_key) FROM prediction_records p "
            "JOIN prediction_settlements s USING(prediction_id) "
            "WHERE s.settlement_status='settled' AND s.paper_profit_units IS NOT NULL "
            "AND json_extract(p.features_json,'$.replay') IS NULL "
            "AND CAST(json_extract(p.features_json,'$.entry_decimal_odds') AS REAL)>1 "
            "AND CAST(json_extract(p.features_json,'$.entry_implied_probability') AS REAL) BETWEEN 0 AND 1"
        ).fetchone()[0]
        clv_rows = conn.execute(
            "SELECT p.features_json, s.closing_probability FROM prediction_records p "
            "JOIN prediction_settlements s USING(prediction_id) "
            "WHERE s.settlement_status='settled' AND s.paper_profit_units IS NOT NULL "
            "AND s.closing_probability IS NOT NULL "
            "AND json_extract(p.features_json,'$.replay') IS NULL "
            "AND CAST(json_extract(p.features_json,'$.entry_decimal_odds') AS REAL)>1 "
            "AND CAST(json_extract(p.features_json,'$.entry_implied_probability') AS REAL) BETWEEN 0 AND 1 "
            "AND p.prediction_id=(SELECT p2.prediction_id FROM prediction_records p2 "
            "JOIN prediction_settlements s2 USING(prediction_id) "
            "WHERE p2.event_key=p.event_key AND s2.settlement_status='settled' "
            "AND s2.paper_profit_units IS NOT NULL "
            "AND json_extract(p2.features_json,'$.replay') IS NULL "
            "AND CAST(json_extract(p2.features_json,'$.entry_decimal_odds') AS REAL)>1 "
            "AND CAST(json_extract(p2.features_json,'$.entry_implied_probability') AS REAL) BETWEEN 0 AND 1 "
            "ORDER BY p2.generated_at DESC LIMIT 1)"
        ).fetchall()
        flags = conn.execute("SELECT COUNT(*) FROM quality_flags WHERE status='open'").fetchone()[0]
        point_row = conn.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN feed_latency_ms IS NOT NULL THEN 1 ELSE 0 END) timed FROM point_events"
        ).fetchone()
    clv_deltas = []
    for row in clv_rows:
        try:
            features = json.loads(row[0] or "{}")
            entry_probability = float(features["entry_implied_probability"])
            close_probability = float(row[1])
            if 0.0 < entry_probability < 1.0 and 0.0 < close_probability < 1.0:
                clv_deltas.append(close_probability - entry_probability)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    avg_clv = sum(clv_deltas) / len(clv_deltas) if clv_deltas else None
    return {
        "frozen_forecasts": int(forecasts),
        "settled_bets": int(settled),
        "average_clv": avg_clv,
        # CLV is a selected-side implied-probability move from the price
        # captured when the forecast was frozen to the last price before start.
        # Require a full 500-event sample before this can open a release gate.
        "clv_samples": len(clv_deltas),
        "positive_clv": bool(len(clv_deltas) >= 500 and avg_clv is not None and avg_clv > 0),
        "open_quality_flags": int(flags),
        "point_events": int(point_row["total"] or 0),
        "point_latency_coverage": float(point_row["timed"] or 0) / float(point_row["total"] or 1),
    }


def append_point_events(rows: Sequence[Mapping[str, object]], path: Path | str = DEFAULT_STORE_PATH) -> int:
    initialize(path)
    inserted = 0
    with connect(path) as conn:
        for row in rows:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO point_events(event_key,sequence_number,observed_at,game_number,"
                "home_points,away_points,server,timeout_state,feed_latency_ms,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(row["event_key"]), int(row["sequence_number"]), str(row["observed_at"]),
                    int(row["game_number"]), int(row["home_points"]), int(row["away_points"]),
                    row.get("server"), row.get("timeout_state"), row.get("feed_latency_ms"),
                    str(row.get("source", "unknown")),
                ),
            )
            inserted += conn.total_changes - before
    return inserted


def append_settlements(rows: Sequence[Mapping[str, object]], path: Path | str = DEFAULT_STORE_PATH) -> int:
    initialize(path)
    inserted = 0
    with connect(path) as conn:
        for row in rows:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO prediction_settlements(prediction_id,settled_at,actual_home,"
                "settlement_status,closing_probability,paper_profit_units) VALUES (?,?,?,?,?,?)",
                (
                    str(row["prediction_id"]), str(row.get("settled_at", utc_now())), int(row["actual_home"]),
                    str(row.get("settlement_status", "settled")), row.get("closing_probability"),
                    row.get("paper_profit_units"),
                ),
            )
            inserted += conn.total_changes - before
    return inserted


def append_quality_flags(rows: Sequence[Mapping[str, object]], path: Path | str = DEFAULT_STORE_PATH) -> int:
    initialize(path)
    inserted = 0
    with connect(path) as conn:
        for row in rows:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO quality_flags(flag_id,entity_type,entity_key,created_at,code,severity,details_json,status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(row["flag_id"]), str(row["entity_type"]), str(row["entity_key"]),
                    str(row.get("created_at", utc_now())), str(row["code"]), str(row["severity"]),
                    json.dumps(row.get("details", {}), ensure_ascii=False, sort_keys=True),
                    str(row.get("status", "open")),
                ),
            )
            inserted += conn.total_changes - before
    return inserted


def odds_history(event_key: str, path: Path | str = DEFAULT_STORE_PATH) -> list[dict[str, object]]:
    if not Path(path).exists():
        return []
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT observed_at,bookmaker,market,selection,line,american_odds,decimal_odds "
            "FROM odds_snapshots WHERE event_key=? ORDER BY observed_at", (event_key,)
        ).fetchall()
    return [dict(row) for row in rows]


def submit_correction(
    entity_type: str,
    entity_key: str,
    requested_change: str,
    evidence_url: str = "",
    *,
    path: Path | str = DEFAULT_STORE_PATH,
) -> str:
    initialize(path)
    created_at = utc_now()
    raw = f"{created_at}|{entity_type}|{entity_key}|{requested_change}"
    from hashlib import sha256

    correction_id = f"cor_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO correction_requests(correction_id,created_at,entity_type,entity_key,requested_change,evidence_url) "
            "VALUES (?,?,?,?,?,?)",
            (correction_id, created_at, entity_type, entity_key, requested_change, evidence_url),
        )
    return correction_id
