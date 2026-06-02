# Pong Odds — Architecture

## Overview
Streamlit app for table tennis match predictions and betting insights. Data is stored in SQLite; all queries go through `db.py`. Odds are fetched from odds-api.io.

## Data Flow
```
odds-api.io (table tennis lines)
        ↓
odds ingestion script → OddsSnapshot → data_files/pong_odds.db (SQLite)
        ↓
db.py (SQLAlchemy ORM + all query helpers)
        ↓
predictions.py → home_page() → Streamlit tabs
        ↓
scripts/export_best_bets.py → data_files/best_bets_today.json
```

## Database Schema (`data_files/pong_odds.db`)
| Table | Key Columns |
|-------|-------------|
| `players` | id, name, country, ranking, elo_rating |
| `matches` | id, player_a_id, player_b_id, match_date, result, event_name |
| `odds_snapshots` | id, match_id, bookmaker, player_name, american_odds, snapshot_time |

## Prediction Model
- Basic Elo rating system (no ML framework)
- `edge` = model_implied_prob - odds_implied_prob
- Displayed confidence tiers match Betting Oracle standard

## Key Components
- `predictions.py` — entry, `st.set_page_config`, `home_page()`
- `db.py` — ALL database queries and ORM models; never put SQL in pages
- `footer.py` — `add_betting_oracle_footer()`

## API Integrations
| Source | Purpose | Key |
|--------|---------|-----|
| odds-api.io | Table tennis betting odds | `ODDS_API_IO_KEY` |

## Storage
- `data_files/pong_odds.db` — SQLite database
- `data_files/logo.png` — app logo
- `data_files/best_bets_today.json` — unified Sports Picks Grid schema

## Security
- API keys in `.env` via `python-dotenv`; never hardcode
- All DB queries parameterised (SQLAlchemy ORM) — no string-formatted SQL
- Validate all user inputs before DB queries
