<a name="top"></a>
<p align="center">
  <img src="data_files/logo.png" width="220" alt="Pong Odds logo">
</p>

# 🎯 Table Tennis Betting Analytics — Pong Odds

## Overview
Pong Odds is a Streamlit analytics app for table tennis betting, built on historical match data and nightly precomputed forecasts. The app delivers:
- fast, search-driven player and tournament exploration
- a precomputed upcoming match betting dashboard
- head-to-head and player form insights
- one-click predictions for any two players

[Back to top](#top)

---

## Pages

### Home
- Summary metrics for matches, players, and tournaments
- Charts showing match volume and top tournaments

### Upcoming Matches
- Uses precomputed predictions from `processed/upcoming_enriched.json`
- Designed to load instantly with no on-demand DB computation
- Updated nightly via GitHub Actions

### Player Stats
- Searchable player selector
- Detailed player record, year-by-year performance, and recent form

### Head to Head
- Compare two players directly with historical H2H and form metrics

### Tournaments
- Searchable tournament selector
- Yearly match distribution and top players for each event

### Predict
- Searchable player pickers for Player 1 and Player 2
- Generates win probability, confidence, and factor breakdown

### Recent Matches
- Lists the latest finished matches from the historical database

[Back to top](#top)

---

## Developer Notes

### Streamlit UI improvements
- Player and tournament pages now use searchable `st.selectbox` inputs.
- The main homepage logo is displayed at the top of the main section only.
- Other pages keep the logo in the sidebar.

### Precompute strategy
- Upcoming match odds are precomputed nightly so users never wait for model execution.
- This keeps page loads immediately responsive.
- Precompute now maintains a lightweight incremental cache (`processed/precompute_cache.json`) for player/pair stats to speed repeated runs.
- Canonical identity mapping (`processed/player_identity_map.json`) helps align player records across sources.

### Prediction quality controls
- Home and Upcoming views include uncertainty-aware filters: minimum confidence, coverage tier, and sample size.
- Top picks now include explainability text (`Why`) sourced from model component weights and data coverage.

### Backtesting
- New `Backtesting` page reports accuracy and Brier score by confidence bucket over a selectable recent window.

### Helpful utilities
- `scripts/check_use_container_width.py` verifies deprecated Streamlit `use_container_width` usage.

[Back to top](#top)



