# Pong Odds implementation matrix

This matrix is the completion audit for the eight requested documents. “Gated” means the complete workflow and UI state exist, but the feature intentionally cannot make a production betting claim until the audit’s named evidence exists.

## Six-month roadmap

| Requirement | Evidence | State |
|---|---|---|
| Today’s fixtures, tournament badge, best pick, live ticker | `pages/6_Upcoming_Matches.py`, `scripts/tt_precompute.py` | Implemented; live pre-match probabilities remain frozen |
| Player profile, Elo history, form, H2H, style, national record | `pages/1_Player_Stats.py`, `pages/2_Head_to_Head.py`, `scripts/classify_player_styles.py` | Implemented; unavailable profile fields show Unknown |
| Value finder, opening/current odds, parlay | `pages/9_Betting_Tools.py`, `scripts/odds_sync.py` | Value/odds implemented; parlay gated off pending joint calibration |
| Bracket, champion path, upset tracker | `pages/10_Tournament_Brackets.py`, `models/frontier_model.py` | Implemented with explicit historical/proxy labels |
| Accuracy by tier, rolling form, Elo vs ITTF | `pages/7_Backtesting.py`, `pages/8_World_Rankings.py` | Implemented |
| Email, nightly refresh, Discord | `.github/workflows/*.yml`, `scripts/notify_picks.py` | Implemented; delivery requires configured webhooks |

## Twelve-month roadmap

| # | Requirement | Evidence | State |
|---:|---|---|---|
| 1 | ITTF rankings, ranking differential | `scripts/ittf_rankings.py`, `scripts/tt_precompute.py`, World Rankings | Implemented; official endpoint remains configurable |
| 2 | Style classification | `scripts/classify_player_styles.py`, profile snapshot schema, Model Lab | Implemented; abstains without verified features |
| 3 | Rich H2H database | historical DB queries, H2H tournament/set-margin UI | Implemented |
| 4 | Set-score model | `set_score_distribution`, Predict, Model Lab | Implemented; betting use gated |
| 5 | Serve-style detector | `serve_receive_adjustment`, service-aware live simulator | Implemented |
| 6 | ITTF-scale Elo | hierarchical `FrontierElo`, replay leaderboard | Implemented |
| 7 | Draw/path analysis | Brackets page and Monte Carlo | Implemented |
| 8 | Form momentum/opponent quality | event-time exponentially weighted win quality | Implemented |
| 9 | DraftKings props | immutable multi-market odds plus Set Props tab | Implemented as research-only |
| 10 | Upset/value alerts | precompute edge alerts at 3%/15% | Implemented when a price exists |
| 11 | Rankings tracker | snapshots, trends, fallback, Elo comparison | Implemented |
| 12 | H2H comparison card | searchable H2H page | Implemented |
| 13 | Bracket viewer | Brackets page | Implemented |
| 14 | Live score/probability | ticker, point-state simulator, latency schema/gate | Score implemented; live wagering gated |
| 15 | Career dashboard | Player Stats | Implemented |
| 16 | Two-hour odds refresh | `frontier-data.yml`, odds archive | Implemented; key required |
| 17 | Weekly rankings sync | `frontier-data.yml`, ranking history | Implemented |
| 18 | Match preview | deterministic evidence-grounded preview in precompute | Implemented |
| 19 | Discord bot | notification script/workflow | Implemented; webhook required |
| 20 | Multi-league coverage | SofaScore/Flashscore collectors and source badges | Implemented |
| 21 | Aging model | `age_adjustment`, Model Lab | Implemented |
| 22 | ROI calendar | settled flat-unit paper calendar | Implemented; empty until priced settlements exist |

## Audit, frontier blueprint, data sources, model suggestions, architecture, and filenames

| Requirement family | Evidence | State |
|---|---|---|
| Event-time Elo/Glicko replay; candidate/time/tournament holdouts | `event_time_replay.py`, `model_candidates.py`, Backtesting | Implemented |
| Stable identities; participant types; aliases; duplicates | audit schema, canonical event keys, identity map, quality audit | Implemented |
| Tour/tier/format/stage/equipment/venue metadata | append-only match/profile schema | Implemented; unknown stays null |
| Immutable odds/forecast/settlement records | `models/audit_store.py` and triggers | Implemented |
| Point/server/game/timeout/deuce state and latency | point-event schema, exact state simulator, Data Quality | Implemented; production live gate closed |
| Hierarchical competition/environment/handedness/recency model | `FrontierElo` context ratings and adjustments | Implemented |
| Fatigue/travel and same-day timeline | `fatigue_adjustment`, Upcoming timeline, Model Lab | Implemented when verified inputs exist |
| Conformal abstention | calibrated-residual support plus sparse fallback | Implemented |
| Source reliability, anomaly quarantine, corrections | Data Quality page and `audit_data_quality.py` | Implemented |
| Forward metrics, calibration, CLV/coverage/release gates | replay report and audit store | Implemented; betting release remains gated |
| SofaScore, Flashscore, ITTF, odds-api.io, licensed imports | scrapers/sync/import adapter | Implemented |
| Style, form, equipment, H2H margin, pressure, blend, calibration | shared model, Predict, replay comparison | Implemented |
| Streamlit 1.45+ navigation and ASCII filenames | `predictions.py`, `pages/`, navigation doc | Implemented |

The audit gates are not placeholders: they prevent unsupported live, props/parlays, ROI, CLV, and staking claims while data accumulates prospectively.
