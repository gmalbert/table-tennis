from __future__ import annotations

from math import log1p

import pandas as pd
import streamlit as st

import db
from footer import add_betting_oracle_footer
from models.frontier_model import bracket_probabilities, tournament_context


st.title("🧩 Tournament Brackets")
st.caption("Historical draw viewer, path simulation, and upset context")

if not db.db_ready():
    st.error("Database not built yet. Run `python scripts/tt_build_db.py`.")
    st.stop()

tournaments = db.all_tournament_names()
selected = st.selectbox("Tournament", tournaments["tournament_name"].tolist(), index=None, placeholder="Search tournaments…")
if selected is None:
    st.info("Select a tournament to inspect its latest recorded draw.")
    st.stop()

matches = db.tournament_matches(selected)
if matches.empty:
    st.warning("No completed matches are available for this tournament.")
    st.stop()

context = tournament_context(selected)
latest_year = matches["date"].astype(str).str[:4].max()
event = matches[matches["date"].astype(str).str[:4] == latest_year].copy()
st.subheader(f"{selected} · {latest_year}")
st.caption(str(context["badge"]))

round_col = "round_name" if event["round_name"].notna().any() else "round"
event["Round"] = event[round_col].fillna("Unspecified").astype(str)
event["Score"] = (
    event["home_sets_won"].fillna(0).astype(int).astype(str)
    + "–"
    + event["away_sets_won"].fillna(0).astype(int).astype(str)
)
event["Winner"] = event.apply(lambda r: r["home_name"] if r["winner"] == "home" else r["away_name"], axis=1)

for round_name, round_df in event.groupby("Round", sort=False):
    with st.expander(f"{round_name} · {len(round_df)} matches", expanded=len(event["Round"].unique()) <= 4):
        st.dataframe(
            round_df[["date", "home_name", "away_name", "Score", "Winner"]].rename(
                columns={"date": "Date", "home_name": "Player A", "away_name": "Player B"}
            ),
            width="stretch",
            hide_index=True,
        )

st.divider()
st.subheader("Champion path simulation")
participants = pd.concat(
    [event[["home_slug", "home_name"]].rename(columns={"home_slug": "slug", "home_name": "name"}),
     event[["away_slug", "away_name"]].rename(columns={"away_slug": "slug", "away_name": "name"})],
    ignore_index=True,
).dropna().drop_duplicates("slug")
records = []
for row in participants.itertuples(index=False):
    player_df = event[(event["home_slug"] == row.slug) | (event["away_slug"] == row.slug)]
    wins = int(
        (((player_df["home_slug"] == row.slug) & (player_df["winner"] == "home")) |
         ((player_df["away_slug"] == row.slug) & (player_df["winner"] == "away"))).sum()
    )
    played = len(player_df)
    rating = 1800.0 + 350.0 * (wins / played if played else 0.5) + 18.0 * log1p(played)
    records.append((str(row.name), rating, played, wins))

if len(records) >= 2:
    field_size = 1 << (min(16, len(records)).bit_length() - 1)
    field_size = max(2, field_size)
    entrants = [(name, rating) for name, rating, _, _ in sorted(records, key=lambda x: x[1], reverse=True)[:field_size]]
    sims = st.slider("Simulations", 1_000, 20_000, 5_000, 1_000)
    probabilities = bracket_probabilities(entrants, simulations=sims)
    table = pd.DataFrame(
        [{"Player": name, "Champion probability": values["champion"]} for name, values in probabilities.items()]
    ).sort_values("Champion probability", ascending=False)
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={"Champion probability": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
    )
    st.caption("Research-only path estimate based on latest-event results; it is not a seeded official draw forecast.")

    # A lower simulated rating beating a higher one is the available seed-line proxy.
    rating_by_name = {name: rating for name, rating, _, _ in records}
    upset = event.apply(
        lambda r: rating_by_name.get(str(r["Winner"]), 1800) < max(
            rating_by_name.get(str(r["home_name"]), 1800), rating_by_name.get(str(r["away_name"]), 1800)
        ),
        axis=1,
    )
    st.metric("Historical upset proxy", f"{upset.mean() * 100:.1f}%", help="Lower event-strength proxy defeated higher proxy")

add_betting_oracle_footer()
