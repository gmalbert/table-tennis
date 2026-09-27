from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

import db
from footer import add_betting_oracle_footer
from frontier_data import load_backtest, load_rankings, ranking_trends


st.title("🌍 World Rankings")
st.caption("Official ITTF snapshots when available, with a clearly labeled historical-data fallback")

rankings, metadata = load_rankings()
if not rankings.empty:
    categories = sorted(rankings["category"].dropna().unique())
    category = st.selectbox("Category", categories)
    view = rankings[rankings["category"] == category].sort_values("rank").copy()
    trends = ranking_trends()
    if not trends.empty:
        view = view.merge(
            trends[trends["category"] == category][["stable_id", "previous_rank"]],
            on="stable_id",
            how="left",
        )
        view["Trend"] = view.apply(
            lambda row: "↑" if pd.notna(row["previous_rank"]) and row["rank"] < row["previous_rank"]
            else "↓" if pd.notna(row["previous_rank"]) and row["rank"] > row["previous_rank"] else "—",
            axis=1,
        )
    else:
        view["Trend"] = "—"
    observed = str(metadata.get("observed_at", ""))[:16].replace("T", " ")
    st.success(f"Official snapshot · {observed} UTC · {len(view):,} players")
    st.dataframe(
        view[["rank", "Trend", "player", "country", "points"]].rename(
            columns={"rank": "Rank", "player": "Player", "country": "Country", "points": "Points"}
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.warning(
        "No official ITTF snapshot has been synced yet. The table below is not an official ranking; "
        "it is a current-year results leaderboard. Run `python scripts/ittf_rankings.py` to replace it."
    )
    fallback = db.top_players_current_year(n=100, min_matches=4)
    if fallback.empty:
        st.info("No current-year matches are available.")
        st.stop()
    fallback.insert(0, "Provisional rank", range(1, len(fallback) + 1))
    st.dataframe(
        fallback[["Provisional rank", "full_name", "wins", "losses", "matches", "win_pct"]].rename(
            columns={"full_name": "Player", "wins": "Wins", "losses": "Losses", "matches": "Matches", "win_pct": "Win %"}
        ),
        width="stretch",
        hide_index=True,
    )

st.divider()
st.subheader("Local Elo vs official rank")
backtest = load_backtest()
elo_rows = backtest.get("elo_leaderboard", []) if isinstance(backtest, dict) else []
if elo_rows:
    elo = pd.DataFrame(elo_rows)
    elo["Elo rank"] = range(1, len(elo) + 1)
    elo["Player"] = elo["slug"].map(db.slug_to_full_name)
    if not rankings.empty:
        official = rankings.copy()
        official["slug"] = (
            official["player"].astype(str).str.casefold().str.replace(r"[^a-z0-9]+", "-", regex=True).str.strip("-")
        )
        official_best = official.sort_values("rank").drop_duplicates("slug")[["slug", "rank"]]
        elo = elo.merge(official_best, on="slug", how="left").rename(columns={"rank": "Official rank"})
    else:
        elo["Official rank"] = pd.NA
    st.dataframe(
        elo[["Elo rank", "Player", "elo", "Official rank", "matches"]].rename(
            columns={"elo": "Replay Elo", "matches": "Replay matches"}
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption("Elo is the final state of the documented chronological replay; official matches appear only where identity resolution is exact.")
else:
    st.info("Run `python scripts/event_time_replay.py` to publish the local Elo leaderboard.")

st.divider()
st.subheader("Ranking distribution")
if not rankings.empty:
    chart = rankings.copy()
    chart["points"] = pd.to_numeric(chart["points"], errors="coerce")
    fig = px.scatter(
        chart.dropna(subset=["points"]),
        x="rank",
        y="points",
        color="category",
        hover_name="player",
        labels={"rank": "World rank", "points": "ITTF points", "category": "Category"},
    )
    fig.update_xaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")
else:
    st.caption(f"Official ranking trend history begins after the first weekly snapshot ({date.today().year}).")

add_betting_oracle_footer()
