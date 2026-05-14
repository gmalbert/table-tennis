# 🏓 Table Tennis Historical Data Scraper

A Python toolkit for pulling historical table tennis match data from **SofaScore** and **Flashscore** — built for betting analysis, model training, and sports research.

---

## Files

| File | Purpose |
|---|---|
| `tt_scraper.py` | Pulls raw data from SofaScore (JSON API) and Flashscore (Playwright) |
| `tt_processor.py` | Flattens raw JSON output into analysis-ready CSV files |

---

## Requirements

```bash
pip install requests playwright tqdm
playwright install chromium
```

> **Python 3.10+** required. Playwright needs Chromium for Flashscore (headless browser).

---

## Quick Start

### 1. Scrape SofaScore (no browser needed — pure JSON)

```bash
python tt_scraper.py sofa --start 2024-01-01 --end 2024-12-31
```

### 2. Scrape Flashscore (requires Playwright/Chromium)

```bash
python tt_scraper.py flash --start 2024-01-01 --end 2024-12-31
```

### 3. Run both sources at once

```bash
python tt_scraper.py all --start 2024-01-01 --end 2024-12-31
```

### 4. Process raw JSON → CSV

```bash
python tt_processor.py --data ./data --output ./processed
```

---

## CLI Reference

### `tt_scraper.py`

```
python tt_scraper.py <source> --start YYYY-MM-DD --end YYYY-MM-DD [options]
```

| Argument | Description |
|---|---|
| `source` | `sofa`, `flash`, or `all` |
| `--start` | Start date (inclusive), format `YYYY-MM-DD` |
| `--end` | End date (inclusive), format `YYYY-MM-DD` |
| `--output` | Root output directory (default: `./data`) |
| `--no-stats` | SofaScore: skip per-event statistics fetch |
| `--h2h` | SofaScore: also fetch head-to-head history per match |
| `--no-detail` | Flashscore: skip match detail pages (faster, no set scores) |
| `--player-ids` | SofaScore: fetch last-match history for specific player IDs |

**Examples:**

```bash
# With H2H history and player profiles
python tt_scraper.py sofa --start 2024-06-01 --end 2024-06-30 --h2h --player-ids 12345 67890

# Flashscore fast mode (match results only, no per-set breakdown)
python tt_scraper.py flash --start 2024-01-01 --end 2024-03-31 --no-detail
```

### `tt_processor.py`

```
python tt_processor.py --data ./data --output ./processed
```

| Argument | Description |
|---|---|
| `--data` | Root folder containing raw scraper output (default: `./data`) |
| `--output` | Destination for CSV files (default: `./processed`) |

---

## Development utilities

### Deprecated Streamlit API check

The repository includes a utility to reject legacy Streamlit layout arguments:

```bash
python scripts/check_use_container_width.py
```

It fails if any Python file still contains `use_container_width`, which should be replaced with `width='stretch'` or `width='content'`.

---

## Output Structure

### Raw data (`./data/`)

```
data/
├── sofascore/
│   └── YYYY-MM-DD/
│       ├── events.json              # All match summaries for the day
│       └── {event_id}/
│           ├── statistics.json      # Per-set scores and match stats
│           └── h2h.json            # Head-to-head history (if --h2h)
└── flashscore/
    └── YYYY-MM-DD/
        └── matches.json             # All matches + set scores for the day
```

### Processed data (`./processed/`)

| File | Description |
|---|---|
| `matches.csv` | One row per match — both sources combined |
| `sets.csv` | One row per set played |
| `players.csv` | Unique player roster with SofaScore IDs |
| `matches_combined.json` | All matches in a single JSON file |

### `matches.csv` columns

| Column | Description |
|---|---|
| `source` | `sofascore` or `flashscore` |
| `event_id` | Source-specific match ID |
| `date` | Match date (`YYYY-MM-DD`) |
| `start_time_utc` | Match start time in UTC |
| `tournament_name` | Tournament or league name |
| `home_name` / `away_name` | Player names |
| `home_sets_won` / `away_sets_won` | Final sets score |
| `home_set1` … `home_set7` | Points won per set (home player) |
| `away_set1` … `away_set7` | Points won per set (away player) |
| `winner` | `home` or `away` |

---

## How It Works

### SofaScore

Hits SofaScore's internal JSON API — the same endpoints the web app uses. No browser required. Returns clean structured JSON per day, with optional drill-down into per-match statistics and H2H history.

Key endpoint pattern:
```
https://www.sofascore.com/api/v1/sport/table-tennis/scheduled-events/{YYYY-MM-DD}
```

### Flashscore

Uses a headless Chromium browser (via Playwright) to render pages and extract match data. Images and fonts are blocked to speed up loading. Cookie consent is handled automatically. The scraper navigates the date selector to reach historical dates, then optionally visits each match detail page for set-by-set scores.

---

## Rate Limiting & Responsible Use

Both scrapers include randomised delays between requests. For large historical pulls:

- **Run in monthly chunks** rather than requesting a full year at once
- **Run overnight** to avoid peak traffic hours
- SofaScore delays: ~2–5 seconds between days, ~1–2.5 seconds between match detail calls
- Flashscore delays: ~3–7 seconds between days, ~2–5 seconds between match detail pages

> ⚠️ Aggressive scraping will result in IP bans. The defaults are conservative — don't lower them.

---

## Finding SofaScore Player & Tournament IDs

Player and tournament IDs appear directly in SofaScore URLs:

```
https://www.sofascore.com/player/fan-zhendong/123456
                                               ^^^^^^ player ID

https://www.sofascore.com/tournament/table-tennis/world/wtt-grand-smash/63218
                                                                         ^^^^^ tournament ID
```

Pass player IDs to `--player-ids` to fetch their full match history beyond the date range.

---

## Known SofaScore Tournament IDs

| Tournament | ID |
|---|---|
| WTT Cup Finals | 63218 |
| WTT Grand Smash Saudi Smash | 63219 |
| WTT Champions | 63220 |

> IDs are stable. New tournaments can be discovered by inspecting the SofaScore URL when browsing a tournament page.

---

## Legal & Ethical Notes

- These are **unofficial, reverse-engineered** endpoints. Neither SofaScore nor Flashscore provides a public API.
- SofaScore's Terms of Service **prohibit commercial use** of their data.
- Flashscore's ToS prohibits automated scraping.
- **This project is for personal research and educational use only.**
- Do not redistribute scraped data or use it in commercial products.

---

## VS Code Tips

If running in VS Code with Claude Sonnet (claude-sonnet-4-6):

- Use the integrated terminal to run scraper commands
- The `./data` and `./processed` folders will appear in the Explorer once the first run completes
- Install the **Parquet Viewer** or **Rainbow CSV** extension to inspect output CSVs directly in VS Code
- For large date ranges, consider using VS Code's terminal split view to monitor progress while working

---

## Roadmap

- [ ] SQLite storage backend (replace raw JSON files)
- [ ] OddsPortal scraper integration (historical closing odds)
- [ ] ITTF results.ittf.link scraper (official rankings + tournament trees)
- [ ] Automated daily refresh via cron / GitHub Actions
- [ ] Player ELO rating calculator
- [ ] Streamlit dashboard for interactive analysis
