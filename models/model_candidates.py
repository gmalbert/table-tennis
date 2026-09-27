"""Forward-block candidate comparison for replay predictions."""

from __future__ import annotations

from math import log
from typing import Sequence

import numpy as np

from models.frontier_model import ReplayPrediction, clamp


def _matrix(predictions: Sequence[ReplayPrediction]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(
        [
            [
                log(clamp(p.probability_home) / (1.0 - clamp(p.probability_home))),
                float(p.tournament_tier),
                float(p.coverage),
                float(p.tournament_tier) * log(clamp(p.probability_home) / (1.0 - clamp(p.probability_home))),
            ]
            for p in predictions
        ],
        dtype=float,
    )
    y = np.asarray([p.actual_home for p in predictions], dtype=int)
    groups = np.asarray([f"{min(p.home_slug,p.away_slug)}|{max(p.home_slug,p.away_slug)}" for p in predictions])
    return x, y, groups


def _metrics(probabilities: np.ndarray, actual: np.ndarray) -> dict[str, float | int]:
    probabilities = np.clip(probabilities, 1e-6, 1.0 - 1e-6)
    return {
        "matches": int(len(actual)),
        "accuracy": float(np.mean((probabilities >= 0.5) == actual)),
        "brier": float(np.mean((probabilities - actual) ** 2)),
        "log_loss": float(-np.mean(actual * np.log(probabilities) + (1 - actual) * np.log(1 - probabilities))),
    }


def compare_candidates(predictions: Sequence[ReplayPrediction]) -> dict[str, dict[str, float | int]]:
    """Compare replay Elo, conditioned Bradley-Terry, and calibrated boosting.

    The final 30% of chronological rows is held out.  Model selection within
    the earlier block uses opponent-pair groups to reduce player memorization.
    """
    if len(predictions) < 500:
        raise ValueError("At least 500 chronological predictions are required")
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold

    ordered = sorted(predictions, key=lambda p: (p.event_time, p.event_key))
    split = int(len(ordered) * 0.70)
    training, testing = ordered[:split], ordered[split:]
    x_train, y_train, groups = _matrix(training)
    x_test, y_test, _ = _matrix(testing)

    baseline = np.asarray([p.probability_home for p in testing], dtype=float)
    conditioned_bt = LogisticRegression(C=0.5, max_iter=1000, class_weight="balanced")
    conditioned_bt.fit(x_train, y_train)
    bt_probabilities = conditioned_bt.predict_proba(x_test)[:, 1]

    unique_groups = len(np.unique(groups))
    folds = max(2, min(5, unique_groups))
    grouped_splits = list(GroupKFold(n_splits=folds).split(x_train, y_train, groups))
    booster = HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        max_iter=150,
        l2_regularization=1.0,
        random_state=42,
    )
    calibrated = CalibratedClassifierCV(booster, method="sigmoid", cv=grouped_splits)
    calibrated.fit(x_train, y_train)
    boost_probabilities = calibrated.predict_proba(x_test)[:, 1]

    tournaments = sorted({p.tournament for p in ordered if p.tournament})
    held_out_tournaments = {
        tournament
        for index, tournament in enumerate(tournaments)
        if index % 10 == 0
    }
    tournament_train = [p for p in ordered if p.tournament not in held_out_tournaments]
    tournament_test = [p for p in ordered if p.tournament in held_out_tournaments]
    tournament_result: dict[str, float | int | str]
    if len(tournament_train) >= 500 and len(tournament_test) >= 100:
        tx_train, ty_train, _ = _matrix(tournament_train)
        tx_test, ty_test, _ = _matrix(tournament_test)
        tournament_model = LogisticRegression(C=0.5, max_iter=1000, class_weight="balanced")
        tournament_model.fit(tx_train, ty_train)
        tournament_result = {
            **_metrics(tournament_model.predict_proba(tx_test)[:, 1], ty_test),
            "held_out_tournaments": len(held_out_tournaments),
        }
    else:
        tournament_result = {
            "matches": len(tournament_test),
            "status": "insufficient tournament-holdout rows",
            "held_out_tournaments": len(held_out_tournaments),
        }

    return {
        "elo_form_blend": _metrics(baseline, y_test),
        "event_conditioned_bradley_terry": _metrics(bt_probabilities, y_test),
        "calibrated_gradient_boosting": _metrics(boost_probabilities, y_test),
        "tournament_holdout_bradley_terry": tournament_result,
        "split": {"training_rows": split, "holdout_rows": len(testing)},
    }
