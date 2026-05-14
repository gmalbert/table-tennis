import streamlit as st
import plotly.express as px

import db

st.title("🏆 Tournaments")

if not db.db_ready():
    st.error("Database not built yet. Run: `python scripts/tt_build_db.py`")
    st.stop()

# ── Tournament selector ───────────────────────────────────────────────────────
all_t = db.all_tournament_names()
_count = dict(zip(all_t["tournament_name"], all_t["match_count"]))

selected = st.selectbox(
    "Tournament",
    options=all_t["tournament_name"].tolist(),
    index=None,
    placeholder="Type to search…",
    format_func=lambda n: f"{n}  ({_count[n]:,} matches)",
    key="t_selector",
)

if not selected:
    st.info("Select a tournament above to get started.")
    st.stop()

# ── Load matches ──────────────────────────────────────────────────────────────
with st.spinner("Loading…"):
    df = db.tournament_matches(selected)

if df.empty:
    st.info("No matches found.")
    st.stop()

meta = all_t[all_t["tournament_name"] == selected].iloc[0]

# ── Stats ─────────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
c1.metric("Total matches", f"{len(df):,}")
c2.metric("First played", meta["first_date"])
c3.metric("Last played",  meta["last_date"])

st.divider()

# ── Matches per year chart ────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("Matches per year")
    df["year"] = df["date"].str[:4]
    yr = df.groupby("year").size().reset_index(name="matches")
    fig = px.bar(yr, x="year", y="matches", labels={"year": "", "matches": "Matches"})
    fig.update_layout(height=280, margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Top players / teams")
    home_wins = df[df["winner"] == "home"][["home_name"]].rename(columns={"home_name": "player"})
    away_wins = df[df["winner"] == "away"][["away_name"]].rename(columns={"away_name": "player"})
    import pandas as pd
    top = pd.concat([home_wins, away_wins])["player"].value_counts().head(10).reset_index()
    top.columns = ["Player", "Wins"]
    st.dataframe(top, width="stretch", hide_index=True)

st.divider()

# ── Match table ───────────────────────────────────────────────────────────────
st.subheader("Results")
display = df.copy()
display["Score"] = display.apply(
    lambda r: f"{r['home_sets_won']}–{r['away_sets_won']}", axis=1
)
display["Winner"] = display.apply(
    lambda r: r["home_name"] if r["winner"] == "home" else r["away_name"], axis=1
)

page_size = 50
total_pages = max(1, (len(display) - 1) // page_size + 1)
page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
start = (page - 1) * page_size
chunk = display.iloc[start : start + page_size]

st.caption(f"Showing {start+1}–{min(start+page_size, len(display))} of {len(display):,}")
st.dataframe(
    chunk[["date", "home_name", "away_name", "Score", "Winner"]]
    .rename(columns={"date": "Date", "home_name": "Home", "away_name": "Away"}),
    width="stretch",
    hide_index=True,
)
