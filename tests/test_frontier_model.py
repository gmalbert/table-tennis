from __future__ import annotations

import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from models.audit_store import append_odds, append_predictions, initialize
from models.frontier_model import (
    FrontierElo,
    GlickoModel,
    bracket_probabilities,
    canonical_event_key,
    conformal_decision,
    game_win_from_point_probability,
    game_win_from_state,
    implied_probability,
    match_win_from_point_prob,
    live_match_probability,
    prediction_metrics,
    release_gates,
    replay_matches,
    set_score_distribution,
)


class FrontierMathTests(unittest.TestCase):
    def test_set_score_distribution_is_complete(self) -> None:
        distribution = set_score_distribution(0.60, 3)
        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=10)
        self.assertGreater(distribution["3-0"], distribution["0-3"])

    def test_deuce_and_match_probabilities_are_symmetric(self) -> None:
        self.assertAlmostEqual(game_win_from_point_probability(0.5, 10, 10), 0.5, places=10)
        self.assertAlmostEqual(match_win_from_point_prob(0.5, 0.5, 5), 0.5, places=10)
        self.assertGreater(game_win_from_point_probability(0.55, 10, 10), 0.5)
        self.assertAlmostEqual(game_win_from_state(0.5, 0.5, 10, 10), 0.5, places=10)
        self.assertAlmostEqual(live_match_probability(0.5, 0.5, best_of=5), 0.5, places=10)
        self.assertGreater(live_match_probability(0.55, 0.52, best_of=5, sets_a=2, sets_b=1), 0.5)

    def test_odds_conversion(self) -> None:
        self.assertAlmostEqual(implied_probability(-110), 110 / 210)
        self.assertAlmostEqual(implied_probability(2.0, "decimal"), 0.5)

    def test_event_key_reconciles_orientation_and_small_time_drift(self) -> None:
        first = canonical_event_key("2026-08-12T12:04:00+00:00", "Ma Long", "Fan Zhendong")
        second = canonical_event_key("2026-08-12T12:12:00+00:00", "Fan Zhendong", "Ma Long")
        self.assertEqual(first, second)

    def test_bracket_probabilities(self) -> None:
        result = bracket_probabilities(
            [("A", 2200), ("B", 2050), ("C", 1950), ("D", 1800)], simulations=2000
        )
        self.assertAlmostEqual(sum(v["champion"] for v in result.values()), 1.0, places=8)
        self.assertGreater(result["A"]["champion"], result["D"]["champion"])

    def test_glicko_updates_after_settlement(self) -> None:
        model = GlickoModel()
        before = float(model.predict("a", "b")["probability_home"])
        model.update("a", "b", 1)
        after = float(model.predict("a", "b")["probability_home"])
        self.assertAlmostEqual(before, 0.5)
        self.assertGreater(after, before)

    def test_release_gates_default_to_safe_modes(self) -> None:
        gates = release_gates(
            frozen_forecasts=999,
            settled_bets=499,
            positive_clv=True,
            robust_low_quality_exclusion=True,
        )
        self.assertFalse(gates["match_winner"]["enabled"])
        self.assertEqual(gates["props_and_parlays"]["mode"], "disabled")
        self.assertEqual(gates["staking"]["mode"], "flat-paper-stakes")

    def test_split_conformal_uses_calibration_residuals(self) -> None:
        result = conformal_decision(0.7, 1.0, alpha=0.1, calibration_residuals=[0.02] * 20)
        self.assertAlmostEqual(result["low"], 0.68)
        self.assertAlmostEqual(result["high"], 0.72)


class ReplayTests(unittest.TestCase):
    def test_replay_predicts_before_update(self) -> None:
        rows = [
            {"source": "test", "event_id": 1, "date": "2026-01-01", "home_slug": "a", "away_slug": "b", "winner": "home", "tournament_name": "WTT"},
            {"source": "test", "event_id": 2, "date": "2026-01-02", "home_slug": "a", "away_slug": "b", "winner": "home", "tournament_name": "WTT"},
        ]
        predictions = replay_matches(rows)
        self.assertAlmostEqual(predictions[0].probability_home, 0.5, places=8)
        self.assertGreater(predictions[1].probability_home, predictions[0].probability_home)
        metrics = prediction_metrics(predictions)
        self.assertEqual(metrics["matches"], 2)
        self.assertTrue(math.isfinite(metrics["log_loss"]))

    def test_replay_orders_start_times_and_batches_simultaneous_matches(self) -> None:
        rows = [
            {
                "source": "test", "event_id": "a-late", "date": "2026-01-01",
                "start_time_utc": "2026-01-01T12:10:00Z", "home_slug": "e", "away_slug": "f",
                "winner": "home", "tournament_name": "WTT",
            },
            {
                "source": "test", "event_id": "z-early", "date": "2026-01-01",
                "start_time_utc": "2026-01-01T12:00:00Z", "home_slug": "a", "away_slug": "b",
                "winner": "away", "tournament_name": "WTT",
            },
            {
                "source": "test", "event_id": "same-1", "date": "2026-01-01",
                "start_time_utc": "2026-01-01T12:05:00Z", "home_slug": "a", "away_slug": "c",
                "winner": "home", "tournament_name": "WTT",
            },
            {
                "source": "test", "event_id": "same-2", "date": "2026-01-01",
                "start_time_utc": "2026-01-01T12:05:00Z", "home_slug": "a", "away_slug": "d",
                "winner": "away", "tournament_name": "WTT",
            },
        ]

        predictions = replay_matches(rows)

        self.assertEqual(
            [prediction.event_time for prediction in predictions],
            [
                "2026-01-01T12:00:00Z",
                "2026-01-01T12:05:00Z",
                "2026-01-01T12:05:00Z",
                "2026-01-01T12:10:00Z",
            ],
        )
        self.assertAlmostEqual(predictions[1].probability_home, predictions[2].probability_home)


class AuditStoreTests(unittest.TestCase):
    def test_forecasts_and_odds_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.db"
            initialize(path)
            inserted = append_predictions(
                [
                    {
                        "prediction_id": "p1",
                        "event_key": "e1",
                        "generated_at": "2026-01-01T00:00:00+00:00",
                        "event_time": "2026-01-02T00:00:00+00:00",
                        "model_version": "test",
                        "probability_home": 0.6,
                        "coverage": 0.8,
                        "abstained": False,
                        "feature_cutoff": "2026-01-01T00:00:00+00:00",
                        "features": {"known_before_event": True},
                    }
                ],
                path,
            )
            self.assertEqual(inserted, 1)
            self.assertEqual(append_predictions([], path), 0)
            self.assertEqual(
                append_odds(
                    [
                        {
                            "snapshot_id": "o1",
                            "event_key": "e1",
                            "observed_at": "2026-01-01T00:00:00+00:00",
                            "bookmaker": "DraftKings",
                            "market": "match_winner",
                            "selection": "A",
                            "decimal_odds": 1.8,
                            "source": "test",
                        }
                    ],
                    path,
                ),
                1,
            )
            conn = sqlite3.connect(path)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE prediction_records SET probability_home=0.7 WHERE prediction_id='p1'")
            conn.close()

    def test_forecast_rejects_post_event_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.db"
            with self.assertRaises(ValueError):
                append_predictions(
                    [
                        {
                            "prediction_id": "late",
                            "event_key": "event",
                            "generated_at": "2026-01-03T00:00:00+00:00",
                            "event_time": "2026-01-02T00:00:00+00:00",
                            "model_version": "test",
                            "probability_home": 0.5,
                            "coverage": 0.5,
                            "abstained": True,
                            "feature_cutoff": "2026-01-01T00:00:00+00:00",
                            "features": {},
                        }
                    ],
                    path,
                )


if __name__ == "__main__":
    unittest.main()
