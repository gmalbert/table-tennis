import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

import db
from footer import add_betting_oracle_footer

st.title("⚔️ Head to Head")

if not db.db_ready():
    st.error("Database not built yet. Run: `python scripts/tt_build_db.py`")
    st.stop()

# ── Player selectors ──────────────────────────────────────────────────────────
players_df = db.all_player_names()
names = players_df["full_name"].tolist()
name_to_slug = dict(zip(players_df["full_name"], players_df["slug"]))

col1, col2 = st.columns(2)

with col1:
    s1 = st.selectbox("Player 1", names, index=None, placeholder="Type to search…")
with col2:
    s2 = st.selectbox("Player 2", names, index=None, placeholder="Type to search…", key="h2h_p2")

if not s1 or not s2:
    st.info("Select both players to see head-to-head history.")
    add_betting_oracle_footer()
    st.stop()

name1, slug1 = s1, name_to_slug[s1]
name2, slug2 = s2, name_to_slug[s2]

if slug1 == slug2:
    st.warning("Please select two different players.")
    st.stop()

# ── Load H2H ──────────────────────────────────────────────────────────────────
with st.spinner("Loading matches…"):
    df = db.h2h_matches(slug1, slug2)

if df.empty:
    st.info(f"No recorded matches between **{name1}** and **{name2}**.")
    st.stop()

# Compute wins for each side
w1 = int(
    ((df["home_slug"] == slug1) & (df["winner"] == "home")).sum() +
    ((df["away_slug"] == slug1) & (df["winner"] == "away")).sum()
)
w2 = len(df) - w1

# ── Headline ──────────────────────────────────────────────────────────────────
st.subheader(f"{name1}  vs  {name2}")

c1, c2, c3 = st.columns(3)
c1.metric(name1, f"{w1} wins")
c2.metric("Total matches", len(df))
c3.metric(name2, f"{w2} wins")

home_margin = df["home_sets_won"].fillna(0) - df["away_sets_won"].fillna(0)
df["p1_set_margin"] = home_margin.where(df["home_slug"] == slug1, -home_margin)
st.caption(
    f"Average set margin for {name1}: {df['p1_set_margin'].mean():+.2f} · "
    f"Latest meeting: {df['date'].max()}"
)

# ── Donut chart ───────────────────────────────────────────────────────────────
fig_donut = go.Figure(go.Pie(
    labels=[name1, name2],
    values=[w1, w2],
    hole=0.55,
    marker_colors=["#3498db", "#e67e22"],
))
fig_donut.update_layout(height=260, margin=dict(t=10, b=10),
                        legend=dict(orientation="h", y=-0.05))
st.plotly_chart(fig_donut, width="stretch")

st.divider()

# ── Wins over time ────────────────────────────────────────────────────────────
st.subheader("Wins per year")
df["year"] = df["date"].str[:4]
df["winner_name"] = df.apply(
    lambda r: name1 if (
        (r["home_slug"] == slug1 and r["winner"] == "home") or
        (r["away_slug"] == slug1 and r["winner"] == "away")
    ) else name2, axis=1
)
yr = df.groupby(["year", "winner_name"]).size().reset_index(name="wins")
fig_yr = px.bar(yr, x="year", y="wins", color="winner_name",
                barmode="group",
                color_discrete_map={name1: "#3498db", name2: "#e67e22"},
                labels={"year": "", "wins": "Wins", "winner_name": ""})
fig_yr.update_layout(height=280, margin=dict(t=10, b=10),
                     legend=dict(orientation="h", y=1.05))
st.plotly_chart(fig_yr, width="stretch")

st.subheader("Tournament-level breakdown")
breakdown = (
    df.groupby("tournament_name")
    .agg(Matches=("winner", "size"), Avg_set_margin=("p1_set_margin", "mean"))
    .sort_values("Matches", ascending=False)
    .head(15)
    .reset_index()
)
breakdown["Player 1 wins"] = breakdown["tournament_name"].map(
    df[df["winner_name"] == name1].groupby("tournament_name").size()
).fillna(0).astype(int)
st.dataframe(
    breakdown.rename(columns={"tournament_name": "Tournament", "Avg_set_margin": "Avg set margin"}),
    width="stretch",
    hide_index=True,
)

st.divider()

# ── Match history table ───────────────────────────────────────────────────────
st.subheader("Match history")
display = df.copy()
display["Winner"] = display["winner_name"]
display["Score"] = display.apply(
    lambda r: f"{r['home_sets_won']}–{r['away_sets_won']}", axis=1
)
display["Home"] = display["home_name"]
display["Away"] = display["away_name"]

st.dataframe(
    display[["date", "Home", "Away", "Score", "Winner", "tournament_name"]]
    .rename(columns={"date": "Date", "tournament_name": "Tournament"}),
    width="stretch",
    hide_index=True,
)

add_betting_oracle_footer()
