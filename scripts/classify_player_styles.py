"""Cluster verified player profile snapshots into three table-tennis styles."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.audit_store import DEFAULT_STORE_PATH, ensure_local

FEATURES = (
    "attack_rate",
    "serve_quality",
    "receive_quality",
    "rally_length_avg",
    "return_quality",
)


def main() -> None:
    ensure_local()
    conn = sqlite3.connect(DEFAULT_STORE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "WITH latest AS (SELECT stable_id,MAX(observed_at) observed_at FROM player_profile_snapshots "
            "WHERE source<>'frontier-style-model' GROUP BY stable_id) "
            "SELECT p.* FROM player_profile_snapshots p JOIN latest l USING(stable_id,observed_at)"
        ).fetchall()
        if len(rows) < 12:
            print("Need at least 12 verified profile snapshots before style clustering")
            return
        matrix = np.asarray([[row[feature] for feature in FEATURES] for row in rows], dtype=float)
        pipeline = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), KMeans(n_clusters=3, random_state=42, n_init=20))
        labels = pipeline.fit_predict(matrix)
        centroids = pipeline[-1].cluster_centers_
        attack_index = int(np.argmax(centroids[:, 0] + centroids[:, 1]))
        defensive_index = int(np.argmax(centroids[:, 3] + centroids[:, 4]))
        style_names = {attack_index: "Aggressive Attacker", defensive_index: "Defensive Looper"}
        for cluster in range(3):
            style_names.setdefault(cluster, "All-Round")
        observed_at = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for row, cluster in zip(rows, labels):
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO player_profile_snapshots(stable_id,observed_at,birth_year,handedness,"
                "playing_style,serve_quality,receive_quality,rally_length_avg,attack_rate,return_quality,"
                "rubber_change_recent,equipment_json,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["stable_id"], observed_at, row["birth_year"], row["handedness"], style_names[int(cluster)],
                    row["serve_quality"], row["receive_quality"], row["rally_length_avg"], row["attack_rate"],
                    row["return_quality"], row["rubber_change_recent"],
                    json.dumps({"derived_from": row["observed_at"], "features": FEATURES}), "frontier-style-model",
                ),
            )
            inserted += conn.total_changes - before
        conn.commit()
        print(f"Appended {inserted} style classifications for {len(rows)} players")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
