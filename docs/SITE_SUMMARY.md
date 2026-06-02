> **AI Onboarding Guide** — See also the project docs folder for data source documentation.

# Pong Odds (Table Tennis) — Site Summary

## What This App Does

Streamlit analytics app for table tennis betting. Built on 10+ years of historical match data, it provides player stats, head-to-head comparisons, and precomputed nightly predictions for upcoming matches. The SQLite database is published to GitHub Releases nightly and auto-downloaded by the app on startup.

## Quick Start

```bash
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1        # Windows
source .venv/bin/activate           # macOS/Linux

# 2. Run the app (auto-downloads latest DB from GitHub Releases)
streamlit run predictions.py
```

For local development with the pipeline:
```bash
python scripts/tt_build_db.py       # Build SQLite DB from processed data
python scripts/tt_precompute.py     # Generate upcoming match predictions
```

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit ≥1.57 (multi-page) |
| ML | XGBoost (precomputed, stored in DB) |
| Data storage | SQLite (auto-downloaded from GitHub Releases nightly) |
| Visualization | Plotly 5.0+ |
| Data processing | pandas, NumPy |

## Key Files

| File | Purpose |
|---|---|
| `predictions.py` | Entry point — home page summary stats |
| `db.py` | DB singleton — auto-downloads latest SQLite from GitHub Releases |
| `pages/1_Player_Stats.py` | Searchable player selector with career stats and form |
| `pages/2_Head_to_Head.py` | Compare any two players with H2H metrics |
| `pages/4_Predict.py` | On-demand match probability for any two players |
| `pages/6_Upcoming_Matches.py` | Precomputed predictions from `processed/upcoming_enriched.json` |
| `scripts/tt_scraper.py` | Historical match data scraper |
| `scripts/tt_processor.py` | Feature engineering and data normalization |
| `scripts/tt_precompute.py` | Nightly predictions generation |
| `scripts/tt_build_db.py` | SQLite DB construction |

## Data Flow

1. **Scraping**: `scripts/tt_scraper.py` collects historical match data from TT aggregator sites
2. **Processing**: `scripts/tt_processor.py` normalizes teams, engineers features
3. **Model training**: XGBoost trained on processed data
4. **Nightly precompute**: `scripts/tt_precompute.py` generates predictions for upcoming matches → writes `processed/upcoming_enriched.json`
5. **DB build**: `scripts/tt_build_db.py` packages everything into SQLite
6. **GitHub Release**: DB published nightly as a release asset
7. **Startup**: `db.py` checks for a newer release and auto-downloads if available

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `GITHUB_TOKEN` | For publishing DB to GitHub Releases (pipeline only) | Required for pipeline |

## Critical Conventions

- The app auto-downloads the DB on startup — do not commit the SQLite file to the repo
- All prediction data is precomputed — pages read from `upcoming_enriched.json` and the SQLite DB; they do not run models
- Use `width='stretch'` for dataframes/charts — `use_container_width` is deprecated

## Current Gaps

- No live betting odds integration — the app shows model win% but no bookmaker comparison
- No Kelly criterion bet sizing
- No explicit tournament tier classification (Grand Slam vs regional events)

## Common Gotchas

- If the GitHub Release download fails at startup, the app will error if no local DB is present; ensure a fallback local DB exists for development
- Player name normalization between historical and upcoming match data may introduce mismatches — check `tt_processor.py` normalization logic if predictions are missing players
