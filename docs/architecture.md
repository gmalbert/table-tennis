# Pong Odds — Architecture

## Runtime flow

```text
SofaScore / Flashscore / ITTF / odds-api.io / licensed imports
                         ↓
raw source JSON → processor → processed/tt.db (historical results)
                         ↓
nightly precompute → processed/upcoming_enriched.json → Streamlit pages
                         ↓
append-only forecasts / odds / settlements → processed/frontier_audit.db
```

`predictions.py` owns `st.set_page_config`, `st.navigation`, and the Home page. ASCII-named modules under `pages/` render the remaining product surfaces. Pages use `db.py` for historical and audit queries; model calculations live under `models/`.

## Storage

`processed/tt.db` is the large, replaceable historical snapshot with `matches`, `sets`, and `players`. `processed/frontier_audit.db` is a small, append-only release artifact with stable identities, ranking/profile snapshots, match metadata, odds snapshots, frozen forecasts, settlements, point events, quality flags, corrections, and notification history. Immutable-table triggers reject updates and deletes.

`processed/upcoming_enriched.json` is the only upcoming-match input read by the UI. It contains precomputed probabilities, tournament tier, uncertainty, abstention, fatigue, reliability, explanations, and preview text.

## Model and evaluation

The current research model blends competition-aware Elo with an event-conditioned logistic score using H2H, recent momentum, overall strength, tier, style, equipment, and fatigue when those inputs exist. Sparse fixtures receive wide intervals and may be abstentions. Glicko, event-conditioned Bradley–Terry/logistic, and calibrated gradient boosting are benchmark candidates.

Evaluation is time-forward. A forecast is generated before its event result updates the state. Candidate comparison uses a chronological outer holdout and participant-pair grouped inner folds. Reporting includes accuracy, Brier score, log loss, calibration error, coverage, tournament tier, and source-quality exclusions.

## Safety and operations

- Keys and webhooks come only from environment/secrets.
- Source rows are quarantined with flags rather than silently corrected.
- Odds and forecast records are immutable and timestamped.
- Live probability requires point state plus latency coverage.
- Match-winner remains paper-only until release gates pass; props/parlays and Kelly staking are disabled.
- GitHub workflows serialize writes to the frontier release artifact through a concurrency group.
