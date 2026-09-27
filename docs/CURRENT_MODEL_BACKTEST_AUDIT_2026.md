# Current-model backtest audit (2026)

## Verdict

The original repository had exceptional result coverage—2,731,274 matches and 10,548,099 set rows—but no prediction or odds table. The original app backtest therefore could not establish that the **current** model made frozen forecasts last year. That historical gap cannot be repaired retroactively; trustworthy current-model betting evidence must accumulate prospectively.

## Implementation update

The evidence gap is now instrumented but the production conclusion is unchanged:

- `models/audit_store.py` creates an append-only odds, forecast, settlement, point-state, identity, metadata, and correction store.
- `scripts/tt_precompute.py` freezes only forecasts generated before event start; `scripts/settle_predictions.py` settles them later.
- `scripts/event_time_replay.py` predicts historical events before updating ratings/form, supports Elo and Glicko, and compares candidate models on forward holdouts. Events with the same timestamp are forecast as a batch before any result in that batch updates ratings.
- The earlier replay and candidate metrics are withdrawn: the old report ordered same-day matches by event ID, allowing later results to affect earlier forecasts. Regenerate all replay and holdout reports before using numeric results as evidence.
- `scripts/tt_precompute.py` now builds its upcoming forecast probabilities from the event-time `FrontierElo` state. The precomputed cache and upcoming fixture snapshot are generated artifacts and are not evidence about current performance.

## Changes justified by the evidence gap

1. Build an event-time replay: for each timestamp group, compute Elo/Glicko and form from strictly earlier groups, then update after settlement.
2. Resolve teams versus individual players and duplicate/cross-source identities before training. Segment tours, competition level, gender, format, and best-of length.
3. Compare Elo, surface/event-conditioned Bradley-Terry, and calibrated gradient boosting with forward time blocks. Use player-level grouping inside tuning to limit memorization.
4. Add immutable odds snapshots and prediction records; data volume without price data cannot validate betting value.

## Betting strategy decision

- **Match winner:** paper-only.
- **Set handicap/game handicap/totals/correct score:** require a serve/set or hierarchical score model and exact format settlement.
- **Live betting:** needs point-level state and latency; historical match rows are insufficient.
- **Props/parlays:** disabled until marginal and joint calibration are demonstrated.
- **Staking:** flat paper stakes; no Kelly.

## Release gate

Forward-season metrics by tour and liquidity tier, market baselines, 1,000+ distinct frozen fixtures, 500+ distinct priced settlements, positive selected-side implied-probability CLV on at least 500 fixtures, and robustness after excluding low-quality/duplicate events. Repeated daily forecasts of the same fixture count once. Historical replay rows never enter the prospective audit store.
