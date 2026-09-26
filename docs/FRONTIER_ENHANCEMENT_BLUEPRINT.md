# Frontier Enhancement Blueprint

## Implemented status

The shared frontier model now includes competition-tier ratings, style and serve/receive interactions, same-day/travel fatigue inputs, exact deuce/set math, coverage-aware abstention, source reliability, stable identities, immutable event-time audit records, anomaly quarantine, a correction workflow, point-feed/latency gates, and time-forward/tournament-tier evaluation. Inputs not present in a verified feed remain unknown rather than being synthesized.

The current documentation covers sources, standard models, calibration, odds, and near-term product work. The unexplored advantage is point/rally state and strong partial pooling across sparse tours.

## Model enhancements

- Hierarchical player ratings by competition, ball/table environment, handedness matchup, and recency.
- Serve/receive state model using point score, server, game number, timeout, and deuce pressure.
- Style interactions from rally length, attack initiation, serve patterns, and return quality where point data exists.
- Travel/fatigue model for repeated same-day matches and cross-country tournament sequences.
- Conformal prediction sets to abstain on new players and low-integrity competitions.

```python
def match_win_from_point_prob(p_serve, p_receive, best_of=5, sims=10000):
    # Production version should simulate service alternation and deuce exactly.
    game_p = 0.5 * p_serve + 0.5 * p_receive
    wins_needed = best_of // 2 + 1
    return sum(comb(best_of, k) * game_p**k * (1-game_p)**(best_of-k)
               for k in range(wins_needed, best_of + 1))
```

## Data and integrity

Store stable player IDs, match/point timestamps, competition tier, format, retirements/walkovers, venue, equipment metadata when verified, and multi-book price snapshots. Add anomaly flags for improbable schedules, duplicated matches, identity collisions, and suspiciously repetitive score patterns. Quarantine rather than silently correcting.

## Product

- Serve/receive matchup panel and deuce simulator.
- Same-day fatigue timeline.
- Competition/source reliability badge.
- Live probability view with explicit feed latency.
- Data-correction workflow for player aliases and duplicate events.

## Gates

Use time-forward and tournament-holdout evaluation with log loss, calibration, CLV, and coverage by tour/tier. Require stable performance after excluding the least reliable competitions, plus audit logs showing that every feature existed before the quoted odds timestamp.
