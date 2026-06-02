"""
Elo rating model for table tennis players.

Implements the standard Elo rating algorithm with:
  - Configurable K-factor (default 32)
  - Expected score formula
  - Bulk rating computation from historical match DataFrame
  - Win probability from Elo differential

Usage:
    from models.elo_model import EloModel, compute_ratings_from_matches, win_probability
    
    model = EloModel(k_factor=32, default_rating=1500)
    ratings = compute_ratings_from_matches(matches_df, model)
    prob = win_probability(ratings.get("player_a"), ratings.get("player_b"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import math

import pandas as pd


# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_RATING: float = 1500.0
K_FACTOR: float = 32.0


# ── Core maths ─────────────────────────────────────────────────────────────────


def expected_score(rating_a: float, rating_b: float) -> float:
    """Return expected score (win probability) for player A against player B."""
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def win_probability(rating_a: float, rating_b: float) -> float:
    """Return win probability for player A given Elo ratings for both players."""
    return expected_score(rating_a, rating_b)


def new_rating(rating: float, actual: float, expected: float, k: float = K_FACTOR) -> float:
    """Return the updated Elo rating after one match."""
    return rating + k * (actual - expected)


# ── EloModel class ─────────────────────────────────────────────────────────────


@dataclass
class EloModel:
    """
    Stateful Elo rating tracker for a set of players.

    Parameters
    ----------
    k_factor : float
        Controls how quickly ratings change (higher = faster adjustment).
        Typical values: 16 (stable), 32 (standard), 40 (active players).
    default_rating : float
        Starting Elo for any player not yet seen.
    """

    k_factor: float = K_FACTOR
    default_rating: float = DEFAULT_RATING
    ratings: dict[str, float] = field(default_factory=dict)
    match_count: dict[str, int] = field(default_factory=dict)

    def get(self, player_slug: str) -> float:
        """Return current Elo rating for a player (default if unseen)."""
        return self.ratings.get(player_slug, self.default_rating)

    def update(self, winner_slug: str, loser_slug: str) -> tuple[float, float]:
        """
        Update ratings after a completed match.

        Returns (new_winner_rating, new_loser_rating).
        """
        r_w = self.get(winner_slug)
        r_l = self.get(loser_slug)

        e_w = expected_score(r_w, r_l)
        e_l = 1.0 - e_w

        # Use lower K for players with many matches (floor at 16)
        effective_k = max(16.0, self.k_factor - 0.1 * min(self.match_count.get(winner_slug, 0), 80))

        new_r_w = new_rating(r_w, 1.0, e_w, effective_k)
        new_r_l = new_rating(r_l, 0.0, e_l, effective_k)

        self.ratings[winner_slug] = new_r_w
        self.ratings[loser_slug] = new_r_l
        self.match_count[winner_slug] = self.match_count.get(winner_slug, 0) + 1
        self.match_count[loser_slug] = self.match_count.get(loser_slug, 0) + 1

        return new_r_w, new_r_l

    def predict(self, player_a_slug: str, player_b_slug: str) -> dict:
        """
        Return a prediction dict for a head-to-head matchup.

        Keys: player_a_prob, player_b_prob, rating_a, rating_b, confidence
        """
        ra = self.get(player_a_slug)
        rb = self.get(player_b_slug)
        prob_a = win_probability(ra, rb)
        prob_b = 1.0 - prob_a

        margin = abs(prob_a - prob_b)
        if margin >= 0.15:
            confidence = "High"
        elif margin >= 0.07:
            confidence = "Medium"
        else:
            confidence = "Low"

        return {
            "player_a_prob": prob_a,
            "player_b_prob": prob_b,
            "rating_a": ra,
            "rating_b": rb,
            "confidence": confidence,
        }

    def all_ratings(self) -> pd.DataFrame:
        """Return a DataFrame of all player ratings sorted descending."""
        rows = [
            {"player_slug": slug, "elo_rating": rating, "matches_played": self.match_count.get(slug, 0)}
            for slug, rating in self.ratings.items()
        ]
        if not rows:
            return pd.DataFrame(columns=["player_slug", "elo_rating", "matches_played"])
        return (
            pd.DataFrame(rows)
            .sort_values("elo_rating", ascending=False)
            .reset_index(drop=True)
        )


# ── Bulk computation ───────────────────────────────────────────────────────────


def compute_ratings_from_matches(
    matches_df: pd.DataFrame,
    model: Optional[EloModel] = None,
    winner_col: str = "winner_slug",
    loser_col: str = "loser_slug",
    date_col: str = "match_date",
) -> EloModel:
    """
    Compute Elo ratings for all players from a historical matches DataFrame.

    The DataFrame must contain winner_slug and loser_slug columns.
    Rows are processed in chronological order (date_col ascending).

    Parameters
    ----------
    matches_df : pd.DataFrame
        Historical matches. Must have columns: winner_col, loser_col.
        Optional: date_col for chronological ordering.
    model : EloModel, optional
        Pre-existing model to update (creates fresh model if None).
    winner_col : str
        Column name for winning player slug.
    loser_col : str
        Column name for losing player slug.
    date_col : str
        Column name for match date (used for sorting only).

    Returns
    -------
    EloModel
        Updated model with ratings for all observed players.
    """
    if model is None:
        model = EloModel()

    df = matches_df.copy()
    if date_col in df.columns:
        df = df.sort_values(date_col)

    for _, row in df.iterrows():
        winner = row.get(winner_col)
        loser = row.get(loser_col)
        if pd.isna(winner) or pd.isna(loser):
            continue
        model.update(str(winner), str(loser))

    return model


def compute_ratings_home_away(
    matches_df: pd.DataFrame,
    model: Optional[EloModel] = None,
    home_col: str = "home_slug",
    away_col: str = "away_slug",
    winner_col: str = "winner",
    date_col: str = "match_date",
) -> EloModel:
    """
    Variant of compute_ratings_from_matches for home/away formatted DataFrames.

    Parameters
    ----------
    winner_col : str
        Column that indicates winner: "home" | "away" | slug value.
    """
    if model is None:
        model = EloModel()

    df = matches_df.copy()
    if date_col in df.columns:
        df = df.sort_values(date_col)

    for _, row in df.iterrows():
        home = row.get(home_col)
        away = row.get(away_col)
        winner_marker = row.get(winner_col)
        if pd.isna(home) or pd.isna(away) or pd.isna(winner_marker):
            continue

        home = str(home)
        away = str(away)
        marker = str(winner_marker).lower()

        if marker == "home":
            model.update(home, away)
        elif marker == "away":
            model.update(away, home)
        else:
            # winner_col contains the actual winner slug
            loser = away if marker == home else home
            model.update(marker, loser)

    return model
