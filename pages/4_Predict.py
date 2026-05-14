"""
Match prediction page.

Algorithm (weighted combination):
    - H2H win rate   — 50 % if ≥5 H2H matches, 25 % if 1-4, 0 % if none
    - Recent form    — last-20 win rate, split evenly among remaining weight
    - Overall record — historical win rate, split evenly among remaining weight
"""

import streamlit as st
import plotly.graph_objects as go

import db

st.title("🔮 Match Prediction")

if not db.db_ready():
    st.error("Database not built yet. Run: `python scripts/tt_build_db.py`")
    st.stop()

players_df = db.all_player_names()
_name_to_slug = dict(zip(players_df["name"], players_df["slug"]))
_player_names = players_df["name"].tolist()


# ── Input ─────────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    name1 = st.selectbox("Player 1", options=_player_names, index=None,
                         placeholder="Type to search…", key="pred_p1")
with c2:
    name2 = st.selectbox("Player 2", options=_player_names, index=None,
                         placeholder="Type to search…", key="pred_p2")

if not name1 or not name2:
    st.info("Select both players to generate a prediction.")
    st.stop()

slug1 = _name_to_slug[name1]
slug2 = _name_to_slug[name2]

if slug1 == slug2:
    st.warning("Please enter two different players.")
    st.stop()

# ── Compute stats ─────────────────────────────────────────────────────────────
with st.spinner("Computing…"):
    h2h_df  = db.h2h_matches(slug1, slug2)
    overall1 = db.overall_win_rate(slug1)
    overall2 = db.overall_win_rate(slug2)
    recent1  = db.recent_win_rate(slug1)
    recent2  = db.recent_win_rate(slug2)

    h2h_total = len(h2h_df)
    if h2h_total > 0:
        h2h_w1 = int(
            ((h2h_df["home_slug"] == slug1) & (h2h_df["winner"] == "home")).sum() +
            ((h2h_df["away_slug"] == slug1) & (h2h_df["winner"] == "away")).sum()
        )
        h2h_rate1 = h2h_w1 / h2h_total
    else:
        h2h_rate1 = 0.5

# Weight scheme
if h2h_total >= 5:
    w_h2h, w_recent, w_overall = 0.50, 0.25, 0.25
elif h2h_total >= 1:
    w_h2h, w_recent, w_overall = 0.25, 0.375, 0.375
else:
    w_h2h, w_recent, w_overall = 0.00, 0.50, 0.50

prob1 = w_h2h * h2h_rate1 + w_recent * recent1 + w_overall * overall1
# Normalise so probs sum to 1
prob2 = 1 - prob1

margin = abs(prob1 - prob2)
if margin >= 0.15:
    confidence, conf_color = "High", "#2ecc71"
elif margin >= 0.07:
    confidence, conf_color = "Medium", "#f39c12"
else:
    confidence, conf_color = "Low", "#e74c3c"

predicted_winner = name1 if prob1 > prob2 else name2

# ── Display ───────────────────────────────────────────────────────────────────
st.subheader(f"{name1}  vs  {name2}")

cc1, cc2, cc3 = st.columns(3)
cc1.metric("Predicted winner", predicted_winner)
cc2.metric("Win probability", f"{max(prob1, prob2)*100:.1f}%")
cc3.metric("Confidence", confidence)

# Gauge / bar
fig = go.Figure(go.Bar(
    x=[prob1 * 100, prob2 * 100],
    y=[name1, name2],
    orientation="h",
    marker_color=["#3498db" if prob1 >= prob2 else "#bdc3c7",
                  "#3498db" if prob2 > prob1  else "#bdc3c7"],
    text=[f"{prob1*100:.1f}%", f"{prob2*100:.1f}%"],
    textposition="auto",
))
fig.update_layout(xaxis=dict(range=[0, 100], title="Win probability (%)"),
                  height=180, margin=dict(t=10, b=10))
st.plotly_chart(fig, width="stretch")

st.divider()

# ── Factor breakdown ──────────────────────────────────────────────────────────
st.subheader("Factor breakdown")

factors = ["H2H win rate", "Recent form (last 20)", "Overall win rate"]
vals1   = [h2h_rate1 * 100, recent1 * 100, overall1 * 100]
vals2   = [(1 - h2h_rate1) * 100, recent2 * 100, overall2 * 100]
weights = [f"{w_h2h*100:.0f}%", f"{w_recent*100:.0f}%", f"{w_overall*100:.0f}%"]
h2h_note = f"({h2h_total} match{'es' if h2h_total != 1 else ''})"

import pandas as pd
breakdown = pd.DataFrame({
    "Factor":  [f"H2H win rate {h2h_note}", "Recent form (last 20)", "Overall win rate"],
    "Weight":  weights,
    name1:     [f"{v:.1f}%" for v in vals1],
    name2:     [f"{v:.1f}%" for v in vals2],
})
st.dataframe(breakdown, width="stretch", hide_index=True)

if h2h_total == 0:
    st.caption(
        "⚠️ These two players have no recorded H2H matches. "
        "Prediction is based purely on recent form and overall record."
    )
