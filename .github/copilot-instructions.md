# Pong Odds — GitHub Copilot Instructions

## Project Overview

**App name:** Pong Odds
**Purpose:** Streamlit app for table tennis match predictions and betting insights.
**Entry point:** `streamlit run predictions.py`
**Part of:** Betting Oracle suite

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit (single-page) |
| Data | SQLite (`data_files/pong_odds.db`) via `db.py` |
| Visualization | Plotly Express |
| Config | python-dotenv (`.env` file) |
| Python | 3.9+ |

---

## File Conventions

### Key files
- `predictions.py` — entry point; sets `st.set_page_config` ONCE. Contains `home_page()` function.
- `db.py` — ALL database queries and ORM models. Import from here; do not put SQL in page files.
- `footer.py` — `add_betting_oracle_footer()` must be called at page bottom.

### Data files
- `data_files/pong_odds.db` — SQLite database (players, matches, odds)
- `data_files/logo.png` — app logo
- `data_files/best_bets_today.json` — unified schema for Sports Picks Grid aggregator

---

## Coding Conventions

- `st.set_page_config()` called ONCE in `predictions.py` only — never in sub-pages
- Use `width='stretch'` for dataframes/charts (not deprecated `use_container_width`)
- All DB access through `db.py` helper functions, wrapped in `@st.cache_data`
- API keys via `python-dotenv`; never hardcode; `.env` is gitignored
- Use `path.exists()` before file operations; return empty DataFrame on failure

## Security
- Never commit `.env` or API keys
- DB path from config, not hardcoded strings
- Validate all user inputs before DB queries (avoid SQL injection via parameterized queries)
