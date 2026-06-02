# Pong Odds — Model Suggested Enhancements

## Priority 1: Elo Model

### Service-Style Adjustment
- Table tennis Elo should be adjusted for playing style: aggressive attackers vs. defensive choppers perform differently against each other than Elo alone suggests.
- Add `style_matchup_adj`: `+0.03` for attack vs. defence, `−0.02` for two defenders.

### Recent Form Decay
- Current Elo uses a fixed K. Add momentum: `k_adjusted = K * (1 + 0.2 * recent_win_rate_adj)` where `recent_win_rate_adj` = (win rate last 10) − 0.5.

### Equipment/Equipment Change
- Rubber changes (common in elite TT) affect performance. Flag `rubber_change_recent` as a binary input when available.

## Priority 2: Match Features

### Head-to-Head Score
- Beyond win/loss, encode average score line. A player who routinely wins 3–0 is more dominant than one who wins 3–2.
- Add `h2h_avg_score_diff`: average game margin in H2H meetings.

### Tournament Pressure Tier
- World Championships, World Tour Finals, and Grand Smashes carry more psychological weight.
- Encode `tournament_tier` (1–4 scale) as a feature.

## Priority 3: New Model

### Logistic Regression Blend
- Build a logistic regression on `[elo_diff, h2h_advantage, tournament_tier, recent_form]`.
- Blend: `pred = 0.65 * elo_prob + 0.35 * lr_prob`.

## Priority 4: Calibration

- Run a calibration curve on past `odds_snapshots` vs. actual outcomes.
- Apply Platt scaling if heavy-favourite overconfidence is detected.
