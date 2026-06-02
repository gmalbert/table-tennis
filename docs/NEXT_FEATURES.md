# Table Tennis Oracle — Next 5 Features to Implement

> **Based on:** Codebase gap analysis as of July 2025

---

## Feature 1: Live Betting Odds Integration

**Why:** The app currently generates match predictions from player ratings but has no live odds comparison. Without market odds, users can't calculate edge or determine whether a bet has value. This is the most critical missing feature for a betting-focused app.

**How:**
1. Add `fetch_odds.py` using The Odds API market key (`table_tennis`) with `ODDS_API_KEY` env var
2. Store fetched odds in `data_files/odds.json` or SQLite via `db.py`
3. Compute `edge = model_prob − implied_prob` for each upcoming match
4. Display in the upcoming matches page: Player A | Player B | Model % | DK Odds | Implied % | Edge
5. Color-code edge: green ≥ 3%, yellow 1–3%, grey < 1%

**Complexity:** Medium

---

## Feature 2: Form Decay Weighting

**Why:** Table tennis form is highly volatile — players go through hot and cold streaks within weeks. The current rating system likely treats matches equally regardless of recency. Exponential time-decay would make ratings more responsive to current form.

**How:**
1. In `db/queries.py`, retrieve `match_date` alongside match results when building player ratings
2. Apply weight = `exp(-λ × days_ago)` where `λ = 0.003` (half-life ≈ 231 days — more aggressive than darts)
3. Use the weighted match history in Elo/rating updates
4. Compare model accuracy with and without decay using a hold-out set of recent matches

**Complexity:** Low

---

## Feature 3: Tournament Tier Classification

**Why:** WTT Grand Smash (Olympics equivalent) and WTT Contender are vastly different competition levels. Training on a mix of all tournament types with equal weight produces noisy ratings, especially for players who primarily play lower-tier events.

**How:**
1. Add `tournament_tier` column to the matches table in `db/schema.py`: `Grand_Smash`, `WTT_Champions`, `WTT_Contender`, `WTT_Star_Contender`, `Other`
2. Apply tournament-tier weight multipliers during rating updates (Grand Smash: 2.0×, Contender: 0.7×)
3. Add a `tier_filter` dropdown to the upcoming matches page to show only high-tier event predictions
4. Display tournament tier badge on each match card

**Complexity:** Medium

---

## Feature 4: Surface / Equipment Regulation Feature

**Why:** The transition from 38mm to 40mm poly balls significantly changed top-spin dynamics and advantaged different player styles. ITTF regulatory changes (rubber limits, ball composition) create regime shifts in historical data that flat ratings miss.

**How:**
1. Add a `ball_regulation` epoch flag to historical matches: `38mm` (before 2015), `40mm_celluloid` (2015–2016), `40mm_plastic` (2016–present)
2. When training the model, weight matches from the most recent regulation era more heavily
3. Add `home_plastic_era_win_pct` and `away_plastic_era_win_pct` as player-level features
4. This is most impactful for players with careers spanning the pre/post 2016 transition

**Complexity:** Medium

---

## Feature 5: Kelly Criterion Bet Sizing

**Why:** Even without live odds today, building the Kelly sizing logic now (using the model edge vs a hypothetical odds level) prepares the app for Feature 1 (odds integration). Kelly sizing is a one-function addition that transforms the app from a predictor to a betting tool.

**How:**
1. Add `utils/kelly.py` with `kelly_fraction(model_prob, decimal_odds) → float` (returns recommended bet as % of bankroll)
2. Apply half-Kelly conservatively (multiply by 0.5) for all bet recommendations
3. Once odds integration (Feature 1) is live, show Kelly stake automatically on each match card
4. Add a bankroll input field in the sidebar (`st.number_input("Bankroll $")`) so Kelly outputs a dollar amount

**Complexity:** Low
