from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from footer import add_betting_oracle_footer
from frontier_data import current_release_gates
from models.frontier_model import (
    FrontierElo,
    age_adjustment,
    fatigue_adjustment,
    game_win_from_point_probability,
    game_win_from_state,
    live_match_probability,
    match_win_from_point_prob,
    set_score_distribution,
    style_matchup_adjustment,
)


st.title("🧪 Model Lab")
st.caption("Transparent set, serve/receive, style, fatigue, aging, and uncertainty experiments")

match_tab, score_tab, live_tab, gate_tab = st.tabs(
    ["Match simulator", "Set-score model", "Serve & deuce", "Release gates"]
)

with match_tab:
    c1, c2 = st.columns(2)
    with c1:
        rating_a = st.slider("Player A Elo", 1200, 2600, 2000, 10)
        style_a = st.selectbox("Player A style", ["Unknown", "Aggressive Attacker", "Defensive Looper", "All-Round"])
        birth_a = st.number_input("Player A birth year (0 = unknown)", 0, 2020, 0)
        same_day_a = st.number_input("Player A prior same-day matches", 0, 6, 0)
        handed_a = st.selectbox("Player A handedness", ["Unknown", "Right", "Left"])
        travel_a = st.number_input("Player A recent travel (km)", 0, 20000, 0, 100)
    with c2:
        rating_b = st.slider("Player B Elo", 1200, 2600, 2000, 10)
        style_b = st.selectbox("Player B style", ["Unknown", "Aggressive Attacker", "Defensive Looper", "All-Round"], key="style_b")
        birth_b = st.number_input("Player B birth year (0 = unknown)", 0, 2020, 0, key="birth_b")
        same_day_b = st.number_input("Player B prior same-day matches", 0, 6, 0, key="same_day_b")
        handed_b = st.selectbox("Player B handedness", ["Unknown", "Right", "Left"], key="handed_b")
        travel_b = st.number_input("Player B recent travel (km)", 0, 20000, 0, 100, key="travel_b")
    env1, env2 = st.columns(2)
    familiarity_a = env1.slider("Player A familiarity with venue/equipment", 0.0, 1.0, 0.5, 0.05)
    familiarity_b = env2.slider("Player B familiarity with venue/equipment", 0.0, 1.0, 0.5, 0.05)
    model = FrontierElo(ratings={"player-a": float(rating_a), "player-b": float(rating_b)})
    age_a = age_adjustment(int(birth_a) or None)
    age_b = age_adjustment(int(birth_b) or None)
    result = model.predict(
        "player-a",
        "player-b",
        style_home=style_a,
        style_away=style_b,
        fatigue_home=fatigue_adjustment(int(same_day_a), float(travel_a)) + 0.05 * (age_a - 1.0),
        fatigue_away=fatigue_adjustment(int(same_day_b), float(travel_b)) + 0.05 * (age_b - 1.0),
        handedness_home=handed_a,
        handedness_away=handed_b,
        environment_familiarity_home=familiarity_a,
        environment_familiarity_away=familiarity_b,
    )
    p = float(result["probability_home"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Player A", f"{p * 100:.1f}%")
    c2.metric("Player B", f"{(1 - p) * 100:.1f}%")
    c3.metric("Decision", "Abstain" if result["abstain"] else "Eligible for paper tracking")
    st.progress(p, text=f"Coverage-aware interval: {result['interval_low']:.1%}–{result['interval_high']:.1%}")
    st.caption(
        f"Style adjustment: {style_matchup_adjustment(style_a, style_b):+.1%} · "
        f"coverage: {result['coverage']:.1%} · aging factors: {age_a:.3f}/{age_b:.3f}"
    )

with score_tab:
    p_set = st.slider("Player A probability of winning a set", 0.05, 0.95, 0.60, 0.01)
    best_of = st.radio("Format", [5, 7], horizontal=True)
    target = best_of // 2 + 1
    scores = set_score_distribution(p_set, target)
    score_df = pd.DataFrame([{"Score": score, "Probability": prob} for score, prob in scores.items()])
    fig = px.bar(score_df, x="Score", y="Probability", text=score_df["Probability"].map(lambda v: f"{v:.1%}"))
    st.plotly_chart(fig, width="stretch")
    st.caption("Exact terminal-score distribution under an independent-set assumption; correct-score betting remains research-only.")

with live_tab:
    p_serve = st.slider("Point win probability on serve", 0.20, 0.80, 0.54, 0.01)
    p_receive = st.slider("Point win probability on receive", 0.20, 0.80, 0.49, 0.01)
    points_a = st.number_input("Current points — A", 0, 30, 9)
    points_b = st.number_input("Current points — B", 0, 30, 9)
    state1, state2, state3 = st.columns(3)
    sets_a = state1.number_input("Sets won — A", 0, 3, 0)
    sets_b = state2.number_input("Sets won — B", 0, 3, 0)
    first_server = state3.selectbox("First server this game", ["A", "B"])
    timeout_for_a = st.checkbox("Player A just used a timeout")
    point_mix = 0.5 * p_serve + 0.5 * p_receive
    game_probability = game_win_from_point_probability(point_mix, int(points_a), int(points_b))
    service_aware_game = game_win_from_state(
        p_serve, p_receive, int(points_a), int(points_b), first_server.casefold(), timeout_for_a
    )
    match_probability = live_match_probability(
        p_serve,
        p_receive,
        best_of=5,
        sets_a=int(sets_a),
        sets_b=int(sets_b),
        points_a=int(points_a),
        points_b=int(points_b),
        first_server=first_server.casefold(),
        timeout_for_a=timeout_for_a,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Neutral current-game", f"{game_probability:.1%}")
    c2.metric("Service-aware game", f"{service_aware_game:.1%}")
    c3.metric("Live BO5 state", f"{match_probability:.1%}")
    st.warning("Live wagering is blocked: no point-level production feed or measured latency is connected.")

with gate_tab:
    summary, gates = current_release_gates()
    gate_rows = [
        {"Market": name.replace("_", " ").title(), "Enabled": item["enabled"], "Mode": item["mode"]}
        for name, item in gates.items()
    ]
    st.dataframe(pd.DataFrame(gate_rows), width="stretch", hide_index=True)
    st.json(summary)
    st.caption("Production requires forward-season/tournament-holdout metrics, 1,000+ frozen forecasts, 500+ settled bets, positive CLV, and robustness exclusions.")

add_betting_oracle_footer()
