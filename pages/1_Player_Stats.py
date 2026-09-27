import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import pandas as pd

import db
from footer import add_betting_oracle_footer
from models.elo_model import expected_score, new_rating
from models.frontier_model import tournament_context
from frontier_data import load_rankings

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
        display_cols = ["full_name", "name", "wins", "losses", "matches", "win_pct"]
        st.dataframe(
            top100[display_cols].rename(columns={
                "full_name": "Full Name",
                "name": "Name",
                "wins": "Wins",
                "losses": "Losses",
                "matches": "Matches",
                "win_pct": "Win %",
            }),
            width="stretch",
            hide_index=True,
        )
    add_betting_oracle_footer()

with tabs[1]:
    # ── Player selector ───────────────────────────────────────────────────────────
    players_df = db.all_player_names()
    _name_to_slug = dict(zip(players_df["full_name"], players_df["slug"]))

    selected_name = st.selectbox("Player", options=players_df["full_name"].tolist(),
                                 index=None, placeholder="Type to search…",
                                 key="ps_player")

    if not selected_name:
        st.info("Select a player above to get started.")
        add_betting_oracle_footer()
        st.stop()

    slug = _name_to_slug[selected_name]

    # ── Load data ─────────────────────────────────────────────────────────────────
    with st.spinner("Loading matches…"):
        df = db.player_matches(slug)

    if df.empty:
        st.warning("No completed matches found for this player.")
        add_betting_oracle_footer()
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
    team_event_mask = df["tournament_name"].str.contains(
        "world championship|olympic|team", case=False, na=False
    )
    team_df = df[team_event_mask]
    team_wins, team_losses = db.player_record(team_df, slug) if not team_df.empty else (0, 0)
    st.caption(
        f"National/team-event record proxy: {team_wins}–{team_losses} · "
        "Style: Unknown (point/rally features are not available for evidence-based classification)"
    )
    final_rows = df[df["round_name"].astype(str).str.contains(r"\bfinal\b", case=False, regex=True, na=False)]
    final_wins = int(
        (((final_rows["home_slug"] == slug) & (final_rows["winner"] == "home")) |
         ((final_rows["away_slug"] == slug) & (final_rows["winner"] == "away"))).sum()
    )
    rankings, _ = load_rankings()
    peak_rank = None
    if not rankings.empty:
        slug_guess = rankings["player"].astype(str).str.casefold().str.replace(r"[^a-z0-9]+", "-", regex=True).str.strip("-")
        ranks = pd.to_numeric(rankings.loc[slug_guess == slug, "rank"], errors="coerce").dropna()
        peak_rank = int(ranks.min()) if not ranks.empty else None
    st.caption(
        f"Recorded finals won: {final_wins} · peak synced ITTF rank: {peak_rank if peak_rank else 'not resolved'}"
    )

    tier_rows = df.copy()
    tier_rows["Competition tier"] = tier_rows["tournament_name"].map(
        lambda name: tournament_context(str(name))["badge"]
    )
    tier_rows["Won"] = (
        ((tier_rows["home_slug"] == slug) & (tier_rows["winner"] == "home")) |
        ((tier_rows["away_slug"] == slug) & (tier_rows["winner"] == "away"))
    )
    tier_record = tier_rows.groupby("Competition tier")["Won"].agg(Matches="size", Wins="sum").reset_index()
    tier_record["Win %"] = 100.0 * tier_record["Wins"] / tier_record["Matches"]
    st.dataframe(tier_record, width="stretch", hide_index=True)

    st.divider()

    st.subheader("Rating history and rolling form")
    chronological = df.sort_values("date").copy()
    rating = 2000.0
    ratings = []
    outcomes = []
    for row in chronological.itertuples(index=False):
        won = (row.home_slug == slug and row.winner == "home") or (row.away_slug == slug and row.winner == "away")
        expected = expected_score(rating, 2000.0)
        rating = new_rating(rating, 1.0 if won else 0.0, expected, 28.0)
        ratings.append(rating)
        outcomes.append(int(won))
    chronological["Elo"] = ratings
    chronological["Won"] = outcomes
    chronological["date_dt"] = pd.to_datetime(chronological["date"], errors="coerce")
    form = (
        chronological.dropna(subset=["date_dt"])
        .set_index("date_dt")["Won"]
        .rolling("90D", min_periods=1)
        .mean()
        .mul(100)
    )
    rc1, rc2 = st.columns(2)
    with rc1:
        fig_elo = px.line(chronological, x="date", y="Elo", title="Opponent-neutral Elo trajectory")
        st.plotly_chart(fig_elo, width="stretch")
    with rc2:
        form_df = form.reset_index(name="Rolling 90-day win %")
        fig_form = px.line(form_df, x="date_dt", y="Rolling 90-day win %", title="Three-month form")
        st.plotly_chart(fig_form, width="stretch")
    st.caption(
        "The profile Elo is an opponent-neutral history visualization; official/ranking-calibrated replay ratings live in the model audit."
    )

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
    add_betting_oracle_footer()
