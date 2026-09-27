<a name="top"></a>
<p align="center">
  <img src="data_files/logo.png" width="220" alt="Pong Odds logo">
</p>

# Pong Odds — Table Tennis Forecasting & Betting Research

Pong Odds is a Streamlit application for auditable table-tennis forecasts, historical analysis, rankings, tournament paths, and evidence-gated paper betting research. The historical SQLite database contains match and set results; upcoming views read a nightly precomputed JSON file so the UI never rebuilds the model during a page request.

The product deliberately separates a probability from a betting recommendation. Match-winner tracking remains paper-only until there are at least 1,000 distinct frozen fixtures, 500 distinct settled, priced paper bets, positive selected-side closing-line value on at least 500 fixtures, and robust results after low-integrity competitions are excluded. Props and parlays are disabled; live probabilities require a measured point-level feed; staking remains flat-paper only.

[Back to top](#top)

## Product surfaces

- **Home / Match Day** — top pre-match paper forecasts, best forecast, feed age, coverage controls, and release status.
- **Upcoming Matches** — precomputed fixtures, tournament-tier badges, reliability, uncertainty interval, abstention, same-day fatigue, set-score research output, deterministic preview, and a 60-second major-event score ticker.
- **Player Stats** — searchable profiles, career record, national/team-event proxy, opponent-neutral Elo trajectory, rolling 90-day form, top opponents, and recent results.
- **Head to Head** — searchable comparison, record, average set margin, yearly results, tournament breakdown, and full match history.
- **World Rankings** — official ITTF snapshots and trend arrows when synced; otherwise a clearly labeled current-year results leaderboard.
- **Tournaments / Brackets** — tournament history, latest draw-like round view, simulated path/champion probabilities, and upset-rate proxy.
- **Predict / Model Lab** — Elo/logistic blend, H2H, form, tournament pressure, styles, equipment changes, fatigue, aging, exact set-score distribution, serve/receive and deuce simulations, conformal-style abstention, and release gates.
- **Betting Tools** — price-based value finder, opening/current odds tracker, disabled parlay gate, and settled flat-unit paper ROI calendar.
- **Backtesting** — event-time replay with a warm-up period, accuracy, Brier score, log loss, calibration error, coverage, and confidence buckets. It is explicitly not called a betting backtest without historical prices.
- **Data Quality** — identity and settlement anomaly checks, source reliability, feed latency, correction requests, secret readiness, and quarantine policy.

[Back to top](#top)

## Modeling and integrity

`models/frontier_model.py` contains the shared dependency-light model primitives:

- ITTF-scale Elo with competition-tier K factors and recent-form adjustment
- Glicko-1 benchmark
- event-conditioned logistic blend and optional forward-block candidate comparison against calibrated gradient boosting
- H2H, exponentially weighted momentum, style interaction, serve/receive, fatigue, aging, and equipment-change inputs
- exact first-to-11/win-by-two deuce math and best-of-5/best-of-7 score distributions
- coverage-aware uncertainty intervals and abstention for sparse/new participants
- tournament bracket Monte Carlo simulation

`scripts/event_time_replay.py` sorts events chronologically, emits a forecast using only prior rows, and only then updates the model. Use `--compare-candidates` to compare the replay blend, event-conditioned Bradley–Terry/logistic model, and calibrated gradient boosting on a forward holdout; grouped inner folds reduce pair memorization.

The prior generated replay report used date-and-ID ordering within each day. It is excluded from current evidence because later same-day results could affect earlier forecasts. Regenerate the report with the corrected timestamp-group replay before citing replay metrics. Historical replay remains research evidence, not frozen-forecast ROI or a production betting claim.

The separate `processed/frontier_audit.db` is append-only for odds, forecasts, settlements, profile snapshots, match metadata, and point events. Database triggers prevent changes or deletion of immutable records. Forecast insertion rejects feature cutoffs after generation and generation after event start.

[Back to top](#top)

## Data sources and automation

- SofaScore and Flashscore collectors provide recent results, fixtures, set scores, rankings when exposed by the feed, and broad domestic/international league coverage.
- `scripts/ittf_rankings.py` normalizes official ranking snapshots from a configurable ITTF endpoint and archives weekly history.
- `scripts/odds_sync.py` archives multi-book `odds-api.io` prices every two hours when `ODDS_API_IO_KEY` is configured.
- `scripts/import_frontier_feed.py` imports normalized licensed/Apify OddsPortal or BetExplorer price exports and future point-level feeds without embedding third-party credentials.
- `scripts/tt_precompute.py` creates `processed/upcoming_enriched.json` and freezes eligible future forecasts.
- `scripts/settle_predictions.py` settles frozen paper forecasts after result refresh.
- `scripts/notify_picks.py` sends an evidence-labeled event preview or paper pick when Discord/email webhook secrets are configured.
- `.github/workflows/frontier-data.yml` runs odds and weekly ranking sync; the existing nightly and database workflows refresh fixtures, results, forecasts, and release artifacts.

Required secrets are never printed: `ODDS_API_IO_KEY`, `DISCORD_WEBHOOK_URL`, and `EMAIL_WEBHOOK_URL`. Optional endpoint variables are `ODDS_API_IO_URL` and `ITTF_RANKINGS_URL`.

[Back to top](#top)

## Local development

```powershell
pip install -r requirements.txt
python scripts/init_frontier_store.py
streamlit run predictions.py
```

Refresh and verify:

```powershell
python scripts/tt_precompute.py
python scripts/event_time_replay.py --days 365 --warmup-days 730 --compare-candidates
python -m unittest discover -s tests -v
python -m py_compile predictions.py db.py footer.py frontier_data.py models/*.py pages/*.py scripts/*.py
```

The Streamlit entry point alone calls `st.set_page_config`; every page filename is ASCII and navigation icons are declared through `st.Page`. The logo appears in the main Home content only and in the sidebar on other pages.

The requirement-by-requirement audit is in [`docs/IMPLEMENTATION_MATRIX.md`](docs/IMPLEMENTATION_MATRIX.md).

[Back to top](#top)
