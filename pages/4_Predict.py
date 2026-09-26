"""Coverage-aware match prediction using the shared frontier model."""

from __future__ import annotations

from collections import deque

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
from footer import add_betting_oracle_footer
from models.frontier_model import FrontierElo, set_score_distribution, tournament_context


st.title("🔮 Match Prediction")
st.caption("Elo/logistic blend with H2H, recent form, style, fatigue, equipment, tournament pressure, and abstention")

if not db.db_ready():
    st.error("Database not built yet. Run: `python scripts/tt_build_db.py`")
    st.stop()

players_df = db.all_player_names()
name_to_slug = dict(zip(players_df["full_name"], players_df["slug"]))
player_names = players_df["full_name"].tolist()

c1, c2 = st.columns(2)
with c1:
    name1 = st.selectbox("Player 1", player_names, index=None, placeholder="Type to search…", key="pred_p1")
with c2:
    name2 = st.selectbox("Player 2", player_names, index=None, placeholder="Type to search…", key="pred_p2")

if not name1 or not name2:
    st.info("Select both players to generate a prediction.")
    add_betting_oracle_footer()
    st.stop()

slug1, slug2 = name_to_slug[name1], name_to_slug[name2]
if slug1 == slug2:
    st.warning("Please select two different players.")
    st.stop()

with st.expander("Match context", expanded=True):
    cx1, cx2, cx3 = st.columns(3)
    tournament = cx1.text_input("Tournament", placeholder="e.g. WTT Grand Smash")
    best_of = cx2.radio("Format", [5, 7], horizontal=True)
    same_day_1 = cx3.number_input(f"{name1} prior same-day matches", 0, 6, 0)
    sx1, sx2, sx3 = st.columns(3)
    style1 = sx1.selectbox(f"{name1} style", ["Unknown", "Aggressive Attacker", "Defensive Looper", "All-Round"])
    style2 = sx2.selectbox(f"{name2} style", ["Unknown", "Aggressive Attacker", "Defensive Looper", "All-Round"])
    same_day_2 = sx3.number_input(f"{name2} prior same-day matches", 0, 6, 0)
    rubber1 = st.checkbox(f"{name1} recent equipment/rubber change")
    rubber2 = st.checkbox(f"{name2} recent equipment/rubber change")

with st.spinner("Computing event-time features…"):
    h2h_df = db.h2h_matches(slug1, slug2)
    p1_matches = db.player_matches(slug1)
    p2_matches = db.player_matches(slug2)
    overall1 = db.player_record(p1_matches, slug1)[0] / len(p1_matches) if len(p1_matches) else 0.5
    overall2 = db.player_record(p2_matches, slug2)[0] / len(p2_matches) if len(p2_matches) else 0.5
    recent1 = db.recent_win_rate(slug1, 20)
    recent2 = db.recent_win_rate(slug2, 20)
    h2h_total = len(h2h_df)
    h2h_w1 = int(
        ((h2h_df["home_slug"] == slug1) & (h2h_df["winner"] == "home")).sum()
        + ((h2h_df["away_slug"] == slug1) & (h2h_df["winner"] == "away")).sum()
    ) if h2h_total else 0
    h2h_rate1 = h2h_w1 / h2h_total if h2h_total else 0.5

model = FrontierElo(
    ratings={slug1: 2000 + 800 * (overall1 - 0.5), slug2: 2000 + 800 * (overall2 - 0.5)},
    counts={slug1: len(p1_matches), slug2: len(p2_matches)},
)
model.recent[slug1] = deque(([1.0] * round(recent1 * 10)) + ([0.0] * (10 - round(recent1 * 10))), maxlen=10)
model.recent[slug2] = deque(([1.0] * round(recent2 * 10)) + ([0.0] * (10 - round(recent2 * 10))), maxlen=10)
pair = tuple(sorted((slug1, slug2)))
canonical_rate = h2h_rate1 if slug1 == pair[0] else 1.0 - h2h_rate1
model.h2h[pair] = ([1] * round(canonical_rate * h2h_total)) + ([0] * (h2h_total - round(canonical_rate * h2h_total)))
result = model.predict(
    slug1,
    slug2,
    tournament=tournament,
    style_home=style1,
    style_away=style2,
    rubber_change_home=rubber1,
    rubber_change_away=rubber2,
    fatigue_home=-0.018 * int(same_day_1),
    fatigue_away=-0.018 * int(same_day_2),
)

prob1 = float(result["probability_home"])
prob2 = 1.0 - prob1
margin = abs(prob1 - prob2)
confidence = "High" if margin >= 0.15 else "Medium" if margin >= 0.07 else "Low"
predicted_winner = name1 if prob1 >= prob2 else name2

st.subheader(f"{name1} vs {name2}")
cc1, cc2, cc3, cc4 = st.columns(4)
cc1.metric("Predicted winner", predicted_winner)
cc2.metric("Win probability", f"{max(prob1, prob2):.1%}")
cc3.metric("Confidence", confidence)
cc4.metric("Decision", "Abstain" if result["abstain"] else "Paper eligible")
st.caption(
    f"{tournament_context(tournament)['badge']} · coverage {result['coverage']:.1%} · "
    f"interval for {name1}: {result['interval_low']:.1%}–{result['interval_high']:.1%}"
)

fig = go.Figure(
    go.Bar(
        x=[prob1 * 100, prob2 * 100],
        y=[name1, name2],
        orientation="h",
        marker_color=["#3498db" if prob1 >= prob2 else "#bdc3c7", "#3498db" if prob2 > prob1 else "#bdc3c7"],
        text=[f"{prob1:.1%}", f"{prob2:.1%}"],
        textposition="auto",
    )
)
fig.update_layout(xaxis=dict(range=[0, 100], title="Win probability (%)"), height=180, margin=dict(t=10, b=10))
st.plotly_chart(fig, width="stretch")

st.subheader("Factor breakdown")
breakdown = pd.DataFrame(
    {
        "Factor": [f"H2H win rate ({h2h_total})", "Recent form", "Overall win rate", "Elo proxy", "Tournament tier"],
        name1: [f"{h2h_rate1:.1%}", f"{recent1:.1%}", f"{overall1:.1%}", f"{result['rating_home']:.0f}", str(result["tournament_tier"])],
        name2: [f"{1-h2h_rate1:.1%}", f"{recent2:.1%}", f"{overall2:.1%}", f"{result['rating_away']:.0f}", str(result["tournament_tier"])],
    }
)
st.dataframe(breakdown, width="stretch", hide_index=True)

set_prob1 = 0.5 + 0.72 * (prob1 - 0.5)
score_probs = set_score_distribution(set_prob1, best_of // 2 + 1)
score_df = pd.DataFrame([{"Score": score, "Probability": probability} for score, probability in score_probs.items()])
st.subheader("Set-score distribution")
st.dataframe(
    score_df.sort_values("Probability", ascending=False),
    width="stretch",
    hide_index=True,
    column_config={"Probability": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
)
st.caption("Set/correct-score outputs are research-only until point-level and exact-settlement gates pass.")

add_betting_oracle_footer()
