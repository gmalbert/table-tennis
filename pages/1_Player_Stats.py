import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date

import db

st.title("👤 Player Stats")

if not db.db_ready():
    st.error("Database not built yet. Run: python scripts/tt_build_db.py")
    st.stop()

tabs = st.tabs([f"Top 100 — {date.today().year}", "Player search"])

with tabs[0]:
    st.subheader(f"Top 100 players by current-year win percentage ({date.today().year})")
    top100 = db.top_players_current_year()
    latest_date = db.current_year_latest_date()
    if top100.empty:
        st.info("No ended matches found for the current year.")
    else:
        caption = "Players are ranked by win percentage with a minimum of 4 matches."
        if latest_date:
            caption += f" Latest ended match in DB for {date.today().year}: {latest_date}."
        st.caption(caption)
        st.dataframe(
            top100.rename(columns={"slug": "Slug", "name": "Player", "wins": "Wins", "losses": "Losses", "matches": "Matches", "win_pct": "Win %"}),
            width="stretch",
            hide_index=True,
        )

with tabs[1]:
    # ── Player selector ───────────────────────────────────────────────────────────
    players_df = db.all_player_names()
    _name_to_slug = dict(zip(players_df["name"], players_df["slug"]))

    selected_name = st.selectbox("Player", options=players_df["name"].tolist(),
                                 index=None, placeholder="Type to search…",
                                 key="ps_player")

    if not selected_name:
        st.info("Select a player above to get started.")
        st.stop()

    slug = _name_to_slug[selected_name]

    # ── Load data ─────────────────────────────────────────────────────────────────
    with st.spinner("Loading matches…"):
        df = db.player_matches(slug)

    if df.empty:
        st.warning("No completed matches found for this player.")
        st.stop()

    wins, losses = db.player_record(df, slug)
    total = wins + losses
    win_pct = wins / total * 100 if total else 0

    # ── Headline metrics ──────────────────────────────────────────────────────────
    st.subheader(selected_name)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total matches", f"{total:,}")
    c2.metric("Wins",   f"{wins:,}")
    c3.metric("Losses", f"{losses:,}")
    c4.metric("Win rate", f"{win_pct:.1f}%")

    st.divider()

    # ── Year-by-year chart ────────────────────────────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Wins & losses by year")
        yr = db.player_wins_by_year(slug)
        fig = go.Figure()
        fig.add_bar(x=yr["year"], y=yr["wins"],   name="Wins",   marker_color="#2ecc71")
        fig.add_bar(x=yr["year"], y=yr["losses"], name="Losses", marker_color="#e74c3c")
        fig.update_layout(barmode="group", margin=dict(t=10, b=10), height=300,
                          legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, width="stretch")

    with right:
        st.subheader("Top opponents")
        df["opponent_name"] = df.apply(
            lambda r: r["away_name"] if r["home_slug"] == slug else r["home_name"], axis=1
        )
        top_opp = df["opponent_name"].value_counts().head(10).reset_index()
        top_opp.columns = ["Opponent", "Matches"]
        st.dataframe(top_opp, width="stretch", hide_index=True)

    st.divider()

    # ── Recent matches ──────────────────────────────────────────────────────────
    st.subheader("Recent 30 matches")
    recent = df.head(30).copy()
    recent["Result"] = recent.apply(
        lambda r: "✅ Win" if (
            (r["home_slug"] == slug and r["winner"] == "home") or
            (r["away_slug"] == slug and r["winner"] == "away")
        ) else "❌ Loss", axis=1
    )
    recent["Score"] = recent.apply(
        lambda r: f"{r['home_sets_won']}–{r['away_sets_won']}", axis=1
    )
    recent["Opponent"] = recent.apply(
        lambda r: r["away_name"] if r["home_slug"] == slug else r["home_name"], axis=1
    )
    recent["Side"] = recent.apply(
        lambda r: "Home" if r["home_slug"] == slug else "Away", axis=1
    )

    st.dataframe(
        recent[["date", "Result", "Opponent", "Side", "Score", "tournament_name"]]
        .rename(columns={"date": "Date", "tournament_name": "Tournament"}),
        width="stretch",
        hide_index=True,
    )
