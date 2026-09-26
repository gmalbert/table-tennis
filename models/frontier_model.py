"""Auditable table-tennis modeling primitives.

The module is intentionally dependency-light and side-effect free.  It contains
the shared calculations used by pre-computation, event-time replay, and the
Streamlit model lab.  Every replay prediction is made before the corresponding
match result is applied, which prevents look-ahead leakage.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from math import comb, exp, log
import random
import re
from typing import Iterable, Mapping, Sequence


K_BY_TIER = {1: 44.0, 2: 36.0, 3: 28.0, 4: 20.0}
STYLE_NAMES = ("Aggressive Attacker", "Defensive Looper", "All-Round", "Unknown")


def clamp(value: float, low: float = 0.02, high: float = 0.98) -> float:
    return min(high, max(low, float(value)))


def stable_player_id(name: str, source: str = "unknown", source_id: str = "") -> str:
    """Return a stable opaque identifier for a source identity."""
    normalized = " ".join(str(name).casefold().split())
    raw = f"{source.casefold()}|{source_id.strip()}|{normalized}"
    return f"plr_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def canonical_event_key(
    start_time: str,
    home_name: str,
    away_name: str,
    competition: str = "",
) -> str:
    """Cross-source event key from time bucket and normalized participants."""
    del competition  # competition labels vary substantially between providers
    normalized_players = sorted(" ".join(str(name).casefold().split()) for name in (home_name, away_name))
    raw_time = str(start_time or "")
    try:
        parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        # Feed timestamps are sometimes timezone-aware and sometimes bare UTC.
        # Normalize both forms before bucketing so forecasts and results from
        # different providers reconcile to the same event key.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        minute_bucket = (parsed.minute // 30) * 30
        time_key = parsed.replace(minute=minute_bucket, second=0, microsecond=0).isoformat()
    except Exception:
        time_key = raw_time[:16]
    raw = f"{time_key}|{normalized_players[0]}|{normalized_players[1]}"
    return "evt_" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def participant_type(name: str) -> str:
    """Conservatively distinguish obvious teams/doubles from individuals."""
    value = " ".join(str(name or "").split()).casefold()
    team_tokens = ("team ", " club", "university", "women's team", "men's team")
    doubles_pattern = re.search(r"\s(?:/|\+|&|and)\s", value)
    return "team_or_doubles" if doubles_pattern or any(t in value for t in team_tokens) else "individual"


def tournament_context(name: str) -> dict[str, object]:
    """Classify a competition into a consistent pressure tier and badge."""
    text = str(name or "").casefold()
    if any(x in text for x in ("olympic", "world championship", "grand smash")):
        return {"tier": 1, "label": "Major", "badge": "Tier 1 · Major"}
    if any(x in text for x in ("world cup", "world tour finals", "wtt finals", "champions")):
        return {"tier": 2, "label": "Elite", "badge": "Tier 2 · Elite"}
    if any(x in text for x in ("wtt", "ittf", "challenger", "contender", "bundesliga")):
        return {"tier": 3, "label": "Tour", "badge": "Tier 3 · Tour"}
    return {"tier": 4, "label": "Domestic / sparse", "badge": "Tier 4 · Domestic"}


def source_reliability(source: str, *, has_sets: bool = False, has_timestamp: bool = True) -> dict[str, object]:
    base = {"ittf": 0.95, "sofascore": 0.82, "flashscore": 0.78, "odds-api.io": 0.88}.get(
        str(source or "").casefold(), 0.55
    )
    score = base + (0.03 if has_sets else 0.0) - (0.12 if not has_timestamp else 0.0)
    score = min(1.0, max(0.0, score))
    label = "High" if score >= 0.85 else "Medium" if score >= 0.68 else "Low"
    return {"score": round(score, 2), "label": label}


def implied_probability(odds: float, odds_format: str = "american") -> float:
    odds = float(odds)
    if odds_format == "decimal":
        if odds <= 1.0:
            raise ValueError("Decimal odds must be greater than 1.0")
        return 1.0 / odds
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    return (-odds) / ((-odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def no_vig_two_way(prob_a: float, prob_b: float) -> tuple[float, float]:
    total = float(prob_a) + float(prob_b)
    if total <= 0:
        raise ValueError("Implied probabilities must have a positive sum")
    return float(prob_a) / total, float(prob_b) / total


def age_adjustment(birth_year: int | None, current_year: int | None = None) -> float:
    if birth_year is None:
        return 1.0
    current_year = current_year or datetime.now().year
    age = current_year - int(birth_year)
    if age < 22:
        return 0.95
    if age <= 32:
        return 1.0
    if age <= 37:
        return 1.0 - (age - 32) * 0.015
    return max(0.85, 1.0 - (age - 32) * 0.025)


def form_momentum(results: Sequence[float], decay: float = 0.30) -> float:
    """Exponentially weighted win quality on a 0-100 scale, newest first."""
    if not results:
        return 50.0
    weights = [exp(-decay * i) for i in range(len(results))]
    return 100.0 * sum(float(r) * w for r, w in zip(results, weights)) / sum(weights)


def style_from_metrics(metrics: Mapping[str, float] | None) -> str:
    """Explainable style classifier that remains useful without model fitting."""
    if not metrics:
        return "Unknown"
    attack = float(metrics.get("attack_rate", 0.0)) + float(metrics.get("forehand_loop_rate", 0.0))
    defence = (1.0 - float(metrics.get("error_rate", 0.5))) + float(metrics.get("rally_length_avg", 0.0)) / 12.0
    if attack >= defence + 0.25:
        return "Aggressive Attacker"
    if defence >= attack + 0.25:
        return "Defensive Looper"
    return "All-Round"


def style_matchup_adjustment(style_a: str, style_b: str) -> float:
    a, b = str(style_a), str(style_b)
    if a == "Aggressive Attacker" and b == "Defensive Looper":
        return 0.03
    if a == "Defensive Looper" and b == "Aggressive Attacker":
        return -0.03
    if a == b == "Defensive Looper":
        return -0.02
    return 0.0


def serve_receive_adjustment(
    serve_quality_a: float | None,
    receive_quality_b: float | None,
    serve_quality_b: float | None = None,
    receive_quality_a: float | None = None,
) -> float:
    values = (serve_quality_a, receive_quality_b, serve_quality_b, receive_quality_a)
    if any(v is None for v in values):
        return 0.0
    advantage_a = float(serve_quality_a) - float(receive_quality_b)
    advantage_b = float(serve_quality_b) - float(receive_quality_a)
    return max(-0.05, min(0.05, 0.08 * (advantage_a - advantage_b)))


def handedness_adjustment(handedness_a: str = "unknown", handedness_b: str = "unknown") -> float:
    a, b = str(handedness_a).casefold(), str(handedness_b).casefold()
    if a.startswith("l") and b.startswith("r"):
        return 0.01
    if a.startswith("r") and b.startswith("l"):
        return -0.01
    return 0.0


def environment_adjustment(familiarity_a: float | None, familiarity_b: float | None) -> float:
    if familiarity_a is None or familiarity_b is None:
        return 0.0
    return max(-0.04, min(0.04, 0.04 * (float(familiarity_a) - float(familiarity_b))))


def fatigue_adjustment(same_day_matches: int = 0, travel_km: float = 0.0, rest_hours: float = 24.0) -> float:
    """Probability adjustment applied to the more fatigued participant."""
    penalty = 0.018 * max(0, int(same_day_matches))
    penalty += min(0.025, max(0.0, float(travel_km)) / 80_000.0)
    if rest_hours < 8:
        penalty += (8.0 - max(0.0, rest_hours)) * 0.003
    return -min(0.08, penalty)


def set_score_distribution(p_set_win: float, sets_to_win: int = 3) -> dict[str, float]:
    """Exact terminal set-score probabilities for either participant."""
    p = clamp(p_set_win, 0.001, 0.999)
    target = int(sets_to_win)
    if target < 1:
        raise ValueError("sets_to_win must be positive")
    out: dict[str, float] = {}
    for losses in range(target):
        games = target + losses
        out[f"{target}-{losses}"] = comb(games - 1, losses) * p**target * (1.0 - p) ** losses
        out[f"{losses}-{target}"] = comb(games - 1, losses) * (1.0 - p) ** target * p**losses
    total = sum(out.values())
    return {score: probability / total for score, probability in out.items()}


def match_win_from_set_probability(p_set_win: float, best_of: int = 5) -> float:
    if best_of <= 0 or best_of % 2 == 0:
        raise ValueError("best_of must be a positive odd number")
    target = best_of // 2 + 1
    dist = set_score_distribution(p_set_win, target)
    return sum(prob for score, prob in dist.items() if int(score.split("-")[0]) == target)


def game_win_from_point_probability(p_point: float, points_a: int = 0, points_b: int = 0) -> float:
    """Exact game win probability with first-to-11 and win-by-two deuce rules."""
    p = clamp(p_point, 0.001, 0.999)
    a, b = int(points_a), int(points_b)
    if (a >= 11 or b >= 11) and abs(a - b) >= 2:
        return 1.0 if a > b else 0.0
    if a >= 10 and b >= 10:
        if a == b:
            return p * p / (p * p + (1.0 - p) ** 2)
        if a == b + 1:
            return p + (1.0 - p) * game_win_from_point_probability(p, a, b + 1)
        if b == a + 1:
            return p * game_win_from_point_probability(p, a + 1, b)
    # Finite dynamic program until deuce; deuce is handled analytically above.
    memo: dict[tuple[int, int], float] = {}

    def solve(x: int, y: int) -> float:
        if (x >= 11 or y >= 11) and abs(x - y) >= 2:
            return 1.0 if x > y else 0.0
        if x >= 10 and y >= 10:
            if x == y:
                return p * p / (p * p + (1.0 - p) ** 2)
            if x == y + 1:
                return p + (1.0 - p) * solve(x, y + 1)
            return p * solve(x + 1, y)
        key = (x, y)
        if key not in memo:
            memo[key] = p * solve(x + 1, y) + (1.0 - p) * solve(x, y + 1)
        return memo[key]

    return solve(a, b)


def game_win_from_state(
    p_serve: float,
    p_receive: float,
    points_a: int = 0,
    points_b: int = 0,
    first_server: str = "a",
    timeout_for_a: bool = False,
) -> float:
    """Exact game probability with two-point service blocks and deuce alternation."""
    serve_p = clamp(p_serve, 0.001, 0.999)
    receive_p = clamp(p_receive, 0.001, 0.999)
    a, b = int(points_a), int(points_b)
    if timeout_for_a:
        serve_p = clamp(serve_p + 0.005, 0.001, 0.999)
        receive_p = clamp(receive_p + 0.005, 0.001, 0.999)
    memo: dict[tuple[int, int], float] = {}

    def a_serves(x: int, y: int) -> bool:
        total = x + y
        block = total if x >= 10 and y >= 10 else total // 2
        starts_a = str(first_server).casefold() in {"a", "home", "player a"}
        return starts_a if block % 2 == 0 else not starts_a

    def solve(x: int, y: int) -> float:
        if (x >= 11 or y >= 11) and abs(x - y) >= 2:
            return 1.0 if x > y else 0.0
        # Collapse repeating deuce cycles analytically while respecting who serves next.
        if x == y and x >= 10:
            p_first = serve_p if a_serves(x, y) else receive_p
            p_second = serve_p if a_serves(x + 1, y) else receive_p
            win_two = p_first * p_second
            lose_two = (1.0 - p_first) * (1.0 - p_second)
            return win_two / (win_two + lose_two)
        key = (x, y)
        if key not in memo:
            p = serve_p if a_serves(x, y) else receive_p
            memo[key] = p * solve(x + 1, y) + (1.0 - p) * solve(x, y + 1)
        return memo[key]

    return solve(a, b)


def live_match_probability(
    p_serve: float,
    p_receive: float,
    *,
    best_of: int = 5,
    sets_a: int = 0,
    sets_b: int = 0,
    points_a: int = 0,
    points_b: int = 0,
    first_server: str = "a",
    timeout_for_a: bool = False,
) -> float:
    """Match probability from current set/point state with exact game scoring."""
    if best_of <= 0 or best_of % 2 == 0:
        raise ValueError("best_of must be a positive odd number")
    target = best_of // 2 + 1
    if sets_a >= target:
        return 1.0
    if sets_b >= target:
        return 0.0
    current_game = game_win_from_state(
        p_serve,
        p_receive,
        points_a,
        points_b,
        first_server,
        timeout_for_a,
    )
    future_game = 0.5 * game_win_from_state(p_serve, p_receive, 0, 0, "a") + 0.5 * game_win_from_state(
        p_serve, p_receive, 0, 0, "b"
    )
    memo: dict[tuple[int, int], float] = {}

    def finish(x: int, y: int) -> float:
        if x >= target:
            return 1.0
        if y >= target:
            return 0.0
        key = (x, y)
        if key not in memo:
            memo[key] = future_game * finish(x + 1, y) + (1.0 - future_game) * finish(x, y + 1)
        return memo[key]

    return current_game * finish(sets_a + 1, sets_b) + (1.0 - current_game) * finish(sets_a, sets_b + 1)


def match_win_from_point_prob(p_serve: float, p_receive: float, best_of: int = 5) -> float:
    """Pre-match approximation using equal service exposure and exact scoring."""
    p_point = 0.5 * clamp(p_serve) + 0.5 * clamp(p_receive)
    return match_win_from_set_probability(game_win_from_point_probability(p_point), best_of)


def conformal_decision(
    probability: float,
    coverage_score: float,
    alpha: float = 0.10,
    calibration_residuals: Sequence[float] | None = None,
) -> dict[str, object]:
    """Split-conformal interval with a conservative sparse-data fallback."""
    p = clamp(probability)
    coverage = min(1.0, max(0.0, float(coverage_score)))
    if calibration_residuals:
        residuals = sorted(abs(float(value)) for value in calibration_residuals)
        quantile_index = min(len(residuals) - 1, max(0, int((1.0 - alpha) * (len(residuals) + 1)) - 1))
        half_width = min(0.40, residuals[quantile_index] + (1.0 - coverage) * 0.08)
    else:
        half_width = min(0.32, 0.06 + (1.0 - coverage) * 0.24 + alpha * 0.10)
    low, high = max(0.0, p - half_width), min(1.0, p + half_width)
    abstain = coverage < 0.40 or (low <= 0.5 <= high)
    return {"low": low, "high": high, "abstain": abstain, "coverage": coverage}


def data_quality_flags(match: Mapping[str, object]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    home, away = str(match.get("home_slug", "")), str(match.get("away_slug", ""))
    if not home or not away:
        flags.append({"code": "missing_identity", "severity": "high"})
    if home and home == away:
        flags.append({"code": "identity_collision", "severity": "critical"})
    if str(match.get("status_description", "")).casefold() in {"walkover", "retired", "cancelled"}:
        flags.append({"code": "non_standard_settlement", "severity": "high"})
    if participant_type(str(match.get("home_name", home))) != participant_type(str(match.get("away_name", away))):
        flags.append({"code": "mixed_participant_type", "severity": "high"})
    if not match.get("date"):
        flags.append({"code": "missing_timestamp", "severity": "high"})
    return flags


@dataclass(frozen=True)
class ReplayPrediction:
    event_key: str
    event_time: str
    home_slug: str
    away_slug: str
    probability_home: float
    actual_home: int
    model_version: str
    tournament_tier: int
    coverage: float
    abstained: bool
    source: str
    tournament: str
    duplicate: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class FrontierElo:
    default_rating: float = 2000.0
    model_version: str = "frontier-elo-v1"
    ratings: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    recent: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=10)))
    h2h: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    context_ratings: dict[tuple[str, int], float] = field(default_factory=dict)
    context_counts: dict[tuple[str, int], int] = field(default_factory=dict)

    def get(self, player: str, ranking: int | None = None) -> float:
        if player in self.ratings:
            return self.ratings[player]
        if ranking and ranking > 0:
            return 2200.0 - 180.0 * log(float(ranking))
        return self.default_rating

    def predict(
        self,
        home: str,
        away: str,
        *,
        tournament: str = "",
        rank_home: int | None = None,
        rank_away: int | None = None,
        style_home: str = "Unknown",
        style_away: str = "Unknown",
        rubber_change_home: bool = False,
        rubber_change_away: bool = False,
        fatigue_home: float = 0.0,
        fatigue_away: float = 0.0,
        handedness_home: str = "unknown",
        handedness_away: str = "unknown",
        environment_familiarity_home: float | None = None,
        environment_familiarity_away: float | None = None,
        serve_quality_home: float | None = None,
        receive_quality_away: float | None = None,
        serve_quality_away: float | None = None,
        receive_quality_home: float | None = None,
    ) -> dict[str, object]:
        tier = int(tournament_context(tournament)["tier"])
        global_home, global_away = self.get(home, rank_home), self.get(away, rank_away)
        contextual_home = self.context_ratings.get((home, tier), global_home)
        contextual_away = self.context_ratings.get((away, tier), global_away)
        home_context_weight = min(0.45, self.context_counts.get((home, tier), 0) / 40.0)
        away_context_weight = min(0.45, self.context_counts.get((away, tier), 0) / 40.0)
        r_home = (1.0 - home_context_weight) * global_home + home_context_weight * contextual_home
        r_away = (1.0 - away_context_weight) * global_away + away_context_weight * contextual_away
        elo_prob = 1.0 / (1.0 + 10.0 ** ((r_away - r_home) / 400.0))
        form_home = form_momentum(list(reversed(self.recent.get(home, ())))) / 100.0
        form_away = form_momentum(list(reversed(self.recent.get(away, ())))) / 100.0
        pair = tuple(sorted((home, away)))
        pair_results = self.h2h.get(pair, [])
        if pair_results:
            canonical_home = home == pair[0]
            h2h_canonical = sum(pair_results) / len(pair_results)
            h2h_home = h2h_canonical if canonical_home else 1.0 - h2h_canonical
        else:
            h2h_home = 0.5
        tier_pressure = (2.5 - tier) * 0.004 * (elo_prob - 0.5)
        feature_score = (
            2.25 * (elo_prob - 0.5)
            + 0.90 * (form_home - form_away)
            + (0.55 if len(pair_results) >= 2 else 0.20) * (h2h_home - 0.5)
            + style_matchup_adjustment(style_home, style_away)
            + handedness_adjustment(handedness_home, handedness_away)
            + environment_adjustment(environment_familiarity_home, environment_familiarity_away)
            + serve_receive_adjustment(
                serve_quality_home,
                receive_quality_away,
                serve_quality_away,
                receive_quality_home,
            )
            + tier_pressure
            + float(fatigue_home) - float(fatigue_away)
            + (-0.015 if rubber_change_home else 0.0)
            + (0.015 if rubber_change_away else 0.0)
        )
        logistic_prob = 1.0 / (1.0 + exp(-feature_score))
        probability = clamp(0.65 * elo_prob + 0.35 * logistic_prob, 0.08, 0.92)
        sample = self.counts.get(home, 0) + self.counts.get(away, 0)
        coverage = min(1.0, 0.70 * sample / 80.0 + 0.30 * min(1.0, len(pair_results) / 8.0))
        interval = conformal_decision(probability, coverage)
        return {
            "probability_home": probability,
            "elo_probability_home": elo_prob,
            "rating_home": r_home,
            "rating_away": r_away,
            "form_home": form_home,
            "form_away": form_away,
            "h2h_home": h2h_home,
            "h2h_matches": len(pair_results),
            "tournament_tier": tier,
            "coverage": coverage,
            "interval_low": interval["low"],
            "interval_high": interval["high"],
            "abstain": interval["abstain"],
        }

    def update(self, home: str, away: str, actual_home: int, *, tournament: str = "") -> None:
        prediction = self.predict(home, away, tournament=tournament)
        tier = int(tournament_context(tournament)["tier"])
        recent_home = list(self.recent.get(home, ()))
        recent_away = list(self.recent.get(away, ()))
        form_adj_home = (sum(recent_home) / len(recent_home) - 0.5) if recent_home else 0.0
        form_adj_away = (sum(recent_away) / len(recent_away) - 0.5) if recent_away else 0.0
        k_home = K_BY_TIER[tier] * (1.0 + 0.2 * form_adj_home)
        k_away = K_BY_TIER[tier] * (1.0 + 0.2 * form_adj_away)
        expected = float(prediction["elo_probability_home"])
        r_home, r_away = self.get(home), self.get(away)
        self.ratings[home] = r_home + k_home * (float(actual_home) - expected)
        self.ratings[away] = r_away + k_away * ((1.0 - float(actual_home)) - (1.0 - expected))
        context_home = self.context_ratings.get((home, tier), r_home)
        context_away = self.context_ratings.get((away, tier), r_away)
        context_expected = 1.0 / (1.0 + 10.0 ** ((context_away - context_home) / 400.0))
        self.context_ratings[(home, tier)] = context_home + 0.6 * k_home * (float(actual_home) - context_expected)
        self.context_ratings[(away, tier)] = context_away + 0.6 * k_away * ((1.0 - float(actual_home)) - (1.0 - context_expected))
        self.context_counts[(home, tier)] = self.context_counts.get((home, tier), 0) + 1
        self.context_counts[(away, tier)] = self.context_counts.get((away, tier), 0) + 1
        self.counts[home] = self.counts.get(home, 0) + 1
        self.counts[away] = self.counts.get(away, 0) + 1
        # Wins over stronger-than-expected opposition receive more momentum
        # credit; losses remain zero. This is still strictly event-time data.
        home_quality = float(actual_home) * (0.5 + 0.5 * (1.0 - expected))
        away_quality = (1.0 - float(actual_home)) * (0.5 + 0.5 * expected)
        self.recent[home].append(home_quality)
        self.recent[away].append(away_quality)
        pair = tuple(sorted((home, away)))
        canonical_home_won = actual_home if home == pair[0] else 1 - actual_home
        self.h2h.setdefault(pair, []).append(int(canonical_home_won))


@dataclass
class GlickoRating:
    rating: float = 2000.0
    deviation: float = 350.0


@dataclass
class GlickoModel:
    """Glicko-1 tracker for event-time benchmark comparisons."""

    model_version: str = "glicko1-v1"
    players: dict[str, GlickoRating] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def get(self, player: str) -> GlickoRating:
        return self.players.get(player, GlickoRating())

    def predict(self, home: str, away: str, *, tournament: str = "", **_: object) -> dict[str, object]:
        home_rating, away_rating = self.get(home), self.get(away)
        q = log(10.0) / 400.0
        g = 1.0 / (1.0 + 3.0 * q * q * away_rating.deviation**2 / (3.141592653589793**2)) ** 0.5
        probability = 1.0 / (1.0 + 10.0 ** (-g * (home_rating.rating - away_rating.rating) / 400.0))
        sample = self.counts.get(home, 0) + self.counts.get(away, 0)
        coverage = min(1.0, sample / 80.0)
        interval = conformal_decision(probability, coverage)
        return {
            "probability_home": probability,
            "elo_probability_home": probability,
            "rating_home": home_rating.rating,
            "rating_away": away_rating.rating,
            "form_home": 0.5,
            "form_away": 0.5,
            "h2h_home": 0.5,
            "h2h_matches": 0,
            "tournament_tier": int(tournament_context(tournament)["tier"]),
            "coverage": coverage,
            "interval_low": interval["low"],
            "interval_high": interval["high"],
            "abstain": interval["abstain"],
        }

    def update(self, home: str, away: str, actual_home: int, *, tournament: str = "") -> None:
        del tournament
        q = log(10.0) / 400.0
        current_home, current_away = self.get(home), self.get(away)

        def updated(player: GlickoRating, opponent: GlickoRating, score: float) -> GlickoRating:
            g = 1.0 / (1.0 + 3.0 * q * q * opponent.deviation**2 / (3.141592653589793**2)) ** 0.5
            expected = 1.0 / (1.0 + 10.0 ** (-g * (player.rating - opponent.rating) / 400.0))
            variance = 1.0 / (q * q * g * g * expected * (1.0 - expected))
            precision = 1.0 / (player.deviation**2) + 1.0 / variance
            deviation = precision ** -0.5
            rating = player.rating + q / precision * g * (score - expected)
            return GlickoRating(rating, max(45.0, deviation))

        self.players[home] = updated(current_home, current_away, float(actual_home))
        self.players[away] = updated(current_away, current_home, 1.0 - float(actual_home))
        self.counts[home] = self.counts.get(home, 0) + 1
        self.counts[away] = self.counts.get(away, 0) + 1


def replay_matches(
    rows: Iterable[Mapping[str, object]],
    *,
    evaluation_start: str = "",
    model: FrontierElo | GlickoModel | None = None,
) -> list[ReplayPrediction]:
    """Replay by event timestamp, predicting a timestamp group before updates."""
    model = model or FrontierElo()
    predictions: list[ReplayPrediction] = []
    seen: set[str] = set()

    def event_timestamp(row: Mapping[str, object]) -> datetime:
        raw = str(row.get("start_time_utc") or row.get("date", ""))
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.min
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    ordered = sorted(rows, key=lambda r: (event_timestamp(r), str(r.get("event_id", ""))))
    # Matches with an identical timestamp are treated as simultaneous: none of
    # their results can influence another forecast in that timestamp group.
    groups: list[list[Mapping[str, object]]] = []
    for row in ordered:
        timestamp = event_timestamp(row)
        if not groups or event_timestamp(groups[-1][0]) != timestamp:
            groups.append([])
        groups[-1].append(row)

    for group in groups:
        settled_in_group: list[tuple[str, str, int, str]] = []
        for row in group:
            home, away = str(row.get("home_slug", "")).strip(), str(row.get("away_slug", "")).strip()
            winner = str(row.get("winner", "")).casefold()
            event_time = str(row.get("start_time_utc") or row.get("date", ""))
            if not home or not away or home == away or winner not in {"home", "away"}:
                continue
            source = str(row.get("source", "unknown"))
            event_id = str(row.get("event_id", ""))
            event_key = (
                canonical_event_key(event_time, home, away)
                if row.get("start_time_utc")
                else f"{source}:{event_id}" if event_id else sha256(
                    f"{event_time}|{home}|{away}|{winner}".encode("utf-8")
                ).hexdigest()[:24]
            )
            if event_key in seen:
                continue
            seen.add(event_key)
            tournament = str(row.get("tournament_name", ""))
            before = model.predict(home, away, tournament=tournament)
            actual_home = int(winner == "home")
            if not evaluation_start or event_time >= evaluation_start:
                predictions.append(
                    ReplayPrediction(
                        event_key=event_key,
                        event_time=event_time,
                        home_slug=home,
                        away_slug=away,
                        probability_home=float(before["probability_home"]),
                        actual_home=actual_home,
                        model_version=model.model_version,
                        tournament_tier=int(before["tournament_tier"]),
                        coverage=float(before["coverage"]),
                        abstained=bool(before["abstain"]),
                        source=source,
                        tournament=tournament,
                        duplicate=False,
                    )
                )
            settled_in_group.append((home, away, actual_home, tournament))
        for home, away, actual_home, tournament in settled_in_group:
            model.update(home, away, actual_home, tournament=tournament)
    return predictions


def prediction_metrics(predictions: Sequence[ReplayPrediction]) -> dict[str, float | int]:
    if not predictions:
        return {"matches": 0, "accuracy": 0.0, "brier": 0.0, "log_loss": 0.0, "ece": 0.0, "coverage": 0.0}
    probs = [clamp(p.probability_home, 1e-6, 1.0 - 1e-6) for p in predictions]
    actual = [p.actual_home for p in predictions]
    accuracy = sum(int((prob >= 0.5) == bool(y)) for prob, y in zip(probs, actual)) / len(probs)
    brier = sum((prob - y) ** 2 for prob, y in zip(probs, actual)) / len(probs)
    log_loss = -sum(y * log(prob) + (1 - y) * log(1 - prob) for prob, y in zip(probs, actual)) / len(probs)
    ece = 0.0
    for low in (0.0, 0.2, 0.4, 0.6, 0.8):
        bucket = [(p, y) for p, y in zip(probs, actual) if low <= p < low + 0.2 or (low == 0.8 and p == 1.0)]
        if bucket:
            ece += len(bucket) / len(probs) * abs(sum(p for p, _ in bucket) / len(bucket) - sum(y for _, y in bucket) / len(bucket))
    non_abstained = sum(not p.abstained for p in predictions)
    return {
        "matches": len(predictions),
        "accuracy": accuracy,
        "brier": brier,
        "log_loss": log_loss,
        "ece": ece,
        "coverage": non_abstained / len(predictions),
    }


def bracket_probabilities(
    entrants: Sequence[tuple[str, float]], *, simulations: int = 5000, seed: int = 42
) -> dict[str, dict[str, float]]:
    """Monte Carlo single-elimination reach/champion probabilities."""
    if len(entrants) < 2 or len(entrants) & (len(entrants) - 1):
        raise ValueError("Entrant count must be a power of two and at least two")
    rng = random.Random(seed)
    names = [name for name, _ in entrants]
    ratings = dict(entrants)
    max_rounds = (len(names)).bit_length() - 1
    reached = {name: [0] * (max_rounds + 1) for name in names}
    for _ in range(max(1, int(simulations))):
        field = names[:]
        rng.shuffle(field)
        for name in field:
            reached[name][0] += 1
        for round_index in range(1, max_rounds + 1):
            next_field: list[str] = []
            for i in range(0, len(field), 2):
                a, b = field[i], field[i + 1]
                p_a = 1.0 / (1.0 + 10.0 ** ((ratings[b] - ratings[a]) / 400.0))
                winner = a if rng.random() < p_a else b
                next_field.append(winner)
                reached[winner][round_index] += 1
            field = next_field
    return {
        name: {f"reach_round_{i}": counts[i] / simulations for i in range(max_rounds + 1)}
        | {"champion": counts[-1] / simulations}
        for name, counts in reached.items()
    }


def release_gates(
    *,
    frozen_forecasts: int,
    settled_bets: int,
    positive_clv: bool,
    robust_low_quality_exclusion: bool,
    joint_calibration: bool = False,
    point_level_feed: bool = False,
) -> dict[str, dict[str, object]]:
    core = frozen_forecasts >= 1000 and settled_bets >= 500 and positive_clv and robust_low_quality_exclusion
    return {
        "match_winner": {"enabled": core, "mode": "production" if core else "paper-only"},
        "set_and_game_markets": {"enabled": core and point_level_feed, "mode": "production" if core and point_level_feed else "research"},
        "live": {"enabled": core and point_level_feed, "mode": "production" if core and point_level_feed else "blocked"},
        "props_and_parlays": {"enabled": core and joint_calibration, "mode": "production" if core and joint_calibration else "disabled"},
        "staking": {"enabled": False, "mode": "flat-paper-stakes"},
    }
