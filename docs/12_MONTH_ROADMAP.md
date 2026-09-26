# Table Tennis (Pong Odds) — 12-Month Feature Roadmap

> Generated: 2026-07-31 | Horizon: August 2026 – July 2027

> Implementation update: the model, schema, pages, imports, settlement loop, and scheduled-workflow scaffolding for all 22 features are present. Data-dependent features abstain or show a research/blocked state when official rankings, point/rally detail, prices, birth/equipment metadata, joint calibration, or notification credentials are absent. This is intentional under the current-model audit.

---

## Q1 (Aug–Oct 2026) — Data Foundation

### Feature 1 — ITTF Rankings Integration

Ingest official ITTF World Rankings for men's and women's singles.
Use ranking differential as primary model feature.

```python
# scrapers/ittf_rankings.py
import requests, pandas as pd
from bs4 import BeautifulSoup

ITTF_RANKINGS_URL = "https://www.ittf.com/rankings/"

def fetch_ittf_world_rankings(category: str = "mens_singles") -> pd.DataFrame:
    resp = requests.get(ITTF_RANKINGS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(resp.text, "lxml")
    rows = []
    for row in soup.find_all("tr")[1:101]:  # Top 100
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) >= 3:
            rows.append({"rank": cells[0], "player": cells[1],
                          "country": cells[2], "points": cells[3] if len(cells) > 3 else "0",
                          "category": category})
    return pd.DataFrame(rows)
```

### Feature 2 — Player Style Classification

Classify players as: aggressive attacker, defensive player, all-round.
Encode style matchup as a model feature.

```python
# analytics/style_classifier.py
import pandas as pd
from sklearn.cluster import KMeans

TT_STYLE_FEATURES = [
    "attack_rate", "backhand_pct", "forehand_loop_rate",
    "serve_variation_score", "rally_length_avg", "error_rate",
]

def classify_tt_player_styles(player_stats: pd.DataFrame) -> pd.DataFrame:
    X = player_stats[TT_STYLE_FEATURES].fillna(player_stats[TT_STYLE_FEATURES].mean())
    km = KMeans(n_clusters=3, random_state=42, n_init=10)
    player_stats["style_cluster"] = km.fit_predict(X)
    STYLE_NAMES = {0: "Aggressive Attacker", 1: "Defensive Looper", 2: "All-Round"}
    player_stats["style"] = player_stats["style_cluster"].map(STYLE_NAMES)
    return player_stats
```

### Feature 3 — Head-to-Head Performance Database

Build comprehensive H2H records by surface type, event level, and
tournament stage.

```python
# db/queries.py
from db.schema import OddsSnapshot  # adapt for TT matches

def get_tt_h2h(player_a: str, player_b: str, session) -> dict:
    from db.schema import Fight as Match  # Reuse schema
    matches = session.query(Match).filter(
        ((Match.fighter_a == player_a) & (Match.fighter_b == player_b)) |
        ((Match.fighter_a == player_b) & (Match.fighter_b == player_a))
    ).all()
    a_wins = sum(1 for m in matches if m.winner == player_a)
    return {"total": len(matches), "a_wins": a_wins, "b_wins": len(matches) - a_wins}
```

### Feature 4 — Set Score Distribution Model

Table tennis uses best-of-5 or best-of-7. Model likely set scores
(3-0, 3-1, 3-2) using player consistency metrics.

```python
# analytics/set_predictor.py
import numpy as np
from scipy.stats import binom

def predict_set_score_tt(p_set_win: float, sets_to_win: int = 3) -> dict:
    """P(3-0), P(3-1), P(3-2) given per-set win probability."""
    p0 = p_set_win ** 3  # 3-0
    p1 = 3 * p_set_win**3 * (1 - p_set_win)  # 3-1 (losing 1 of first 4)
    p2 = 6 * p_set_win**3 * (1 - p_set_win)**2  # 3-2 (simplified)
    total = p0 + p1 + p2
    return {"3-0": p0/total, "3-1": p1/total, "3-2": p2/total}
```

### Feature 5 — Serve Style Advantage Detector

In table tennis, certain serve styles dominate against certain receive
styles. Build a serve-receive matchup advantage matrix.

---

## Q2 (Nov 2026 – Jan 2027) — Modeling Enhancement

### Feature 6 — Elo Rating System for TT

Build ITTF-calibrated Elo system. Start each player at ranking-based
initial Elo. Use K=40 for world-class events, K=20 for smaller events.

```python
# analytics/tt_elo.py
import pandas as pd

K_BY_LEVEL = {"World Championships": 40, "Olympics": 50,
               "World Cup": 35, "ITTF World Tour": 30, "National": 15}

def build_tt_elo(matches: pd.DataFrame) -> pd.DataFrame:
    elo = {}
    records = []
    for _, m in matches.sort_values("match_date").iterrows():
        pa, pb = m["player_a"], m["player_b"]
        ea = elo.get(pa, 2000)  # TT ratings are higher (~2000 range)
        eb = elo.get(pb, 2000)
        exp_a = 1 / (1 + 10 ** ((eb - ea) / 400))
        k = K_BY_LEVEL.get(m.get("event_level", "ITTF World Tour"), 30)
        actual_a = 1.0 if m["winner"] == pa else 0.0
        elo[pa] = ea + k * (actual_a - exp_a)
        elo[pb] = eb + k * ((1 - actual_a) - (1 - exp_a))
        records.append({"match_id": m.get("match_id"), "elo_a": elo[pa], "elo_b": elo[pb]})
    return pd.DataFrame(records)
```

### Feature 7 — Tournament Draw & Path Analysis

For seeded tournaments, compute each player's projected path difficulty
and probability of reaching each round.

### Feature 8 — Form Momentum Metric

Exponentially weighted recent match results. Factor in difficulty of
opponents beaten (adjusted win quality score).

```python
# analytics/form.py
import numpy as np, pandas as pd

def compute_tt_momentum(player: str, results: pd.DataFrame, n: int = 10) -> float:
    recent = (
        results[(results["player_a"] == player) | (results["player_b"] == player)]
        .sort_values("match_date", ascending=False)
        .head(n)
    )
    if recent.empty:
        return 50.0
    wins = ((recent["player_a"] == player) & (recent["winner"] == player) |
            (recent["player_b"] == player) & (recent["winner"] == player)).values.astype(float)
    weights = np.exp(-0.3 * np.arange(len(wins)))
    return float(np.average(wins, weights=weights)) * 100
```

### Feature 9 — DraftKings Props Integration

Fetch DK table tennis match props (set totals, handicap sets) and
compare against model probabilities.

### Feature 10 — Upset Probability Alert

Flag matches where model probability diverges significantly from odds-implied
probability (>15% gap). Surface as value bet alerts.

---

## Q3 (Feb–Apr 2027) — Dashboard & Analytics

### Feature 11 — World Rankings Tracker

Display current ITTF rankings with trend arrows. Player detail page
with career highlights, win rates, and Elo history.

### Feature 12 — Head-to-Head Comparison Card

Rich H2H comparison for any two players: record, average set score,
tournament level breakdown, and model win probability.

### Feature 13 — Tournament Bracket Viewer

Interactive bracket for major ITTF events. Click any match to see
model prediction and odds comparison.

### Feature 14 — Live Match Score Tracker

During major ITTF events, display live scores via table tennis API.
Update model win probability as sets complete.

### Feature 15 — Career Statistics Dashboard

Player career page: tournament wins by level, peak ranking, win rate
by year, and best performances.

---

## Q4 (May–Jul 2027) — Automation

### Feature 16 — Automated Odds Refresh

Fetch The Odds API every 2 hours for major TT events. Archive odds
history for CLV analysis.

### Feature 17 — Weekly Rankings Sync

Automated Monday morning ITTF ranking sync via GitHub Actions.
Trigger Elo recalibration after each ranking update.

### Feature 18 — AI Match Preview

Generate brief AI match previews for top-level matches including
H2H context, current form, and model recommendation.

### Feature 19 — Discord Alert Bot

Post high-confidence TT picks to Discord before match start time.
Include model edge, odds, and key matchup factors.

### Feature 20 — Multi-League Coverage

Expand beyond ITTF to include Bundesliga Table Tennis, Chinese Super
League, and major domestic leagues.

### Feature 21 — Player Aging Model

Track performance decline by age for veteran players. TT players
often stay competitive into their 30s — model differently from combat sports.

```python
# analytics/aging.py
def tt_age_adjustment(birth_year: int, current_year: int = 2026) -> float:
    age = current_year - birth_year
    if age < 22:
        return 0.95  # developing
    elif age <= 32:
        return 1.0   # peak
    elif age <= 37:
        return 1.0 - (age - 32) * 0.015
    else:
        return max(0.85, 1.0 - (age - 32) * 0.025)
```

### Feature 22 — Betting ROI Calendar

Monthly performance tracking. Green/red calendar cells showing P&L
per day. Best and worst day analysis.

---

## Timeline Summary

| Quarter | Focus | Key Deliverables |
|---------|-------|-----------------|
| Q1 Aug–Oct 2026 | Data foundation | ITTF rankings, style classifier, H2H database, set score model, serve advantage |
| Q2 Nov 2026–Jan 2027 | Modeling | Elo system, draw analysis, form momentum, DK props, upset alerts |
| Q3 Feb–Apr 2027 | Dashboard | Rankings tracker, H2H card, bracket viewer, live scores, career stats |
| Q4 May–Jul 2027 | Automation | Odds refresh, ranking sync, AI preview, Discord bot, multi-league, aging model, ROI calendar |
