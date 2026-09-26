from __future__ import annotations

import math
import pandas as pd
import plotly.express as px
import streamlit as st

from footer import add_betting_oracle_footer
from frontier_data import current_release_gates, latest_odds, load_upcoming, odds_movement
from models.audit_store import DEFAULT_STORE_PATH
from models.frontier_model import implied_probability
from models.frontier_model import set_score_distribution
import db


st.title("🧰 Betting Tools")
st.caption("Price comparison and paper-tracking tools governed by the current-model audit")

summary, gates = current_release_gates()
mode = str(gates["match_winner"]["mode"])
st.info(
    f"Match-winner mode: **{mode}** · {summary['frozen_forecasts']:,}/1,000 frozen forecasts · "
    f"{summary['settled_bets']:,}/500 settled paper bets · staking remains flat-paper only."
)

value_tab, odds_tab, props_tab, parlay_tab, roi_tab = st.tabs(
    ["Value finder", "Odds tracker", "Set props", "Parlay gate", "Paper ROI calendar"]
)

with value_tab:
    fixtures, _ = load_upcoming()
    odds = latest_odds()
    min_edge = st.slider("Minimum model edge", 0.0, 20.0, 3.0, 0.5) / 100.0
    if fixtures.empty:
        st.warning("No precomputed fixtures are available.")
    elif odds.empty:
        st.warning(
            "No immutable odds snapshots exist yet. Configure `ODDS_API_IO_KEY` and run "
            "`python scripts/odds_sync.py`; model probabilities are intentionally not presented as value without a price."
        )
    else:
        fixtures = fixtures.copy()
        fixtures["Model probability"] = pd.to_numeric(
            fixtures["Win %"].astype(str).str.rstrip("%"), errors="coerce"
        ) / 100.0
        merged = fixtures.merge(odds, left_on="Event Key", right_on="event_key", how="inner")
        merged = merged[merged["selection"].str.casefold() == merged["Favourite"].str.casefold()].copy()
        merged["Market probability"] = merged.apply(
            lambda r: 1.0 / r["decimal_odds"] if pd.notna(r["decimal_odds"]) and r["decimal_odds"] > 1
            else implied_probability(r["american_odds"]) if pd.notna(r["american_odds"]) else math.nan,
            axis=1,
        )
        merged["Edge"] = merged["Model probability"] - merged["Market probability"]
        merged = merged[merged["Edge"] >= min_edge].sort_values("Edge", ascending=False)
        st.dataframe(
            merged[["Tournament", "Home", "Away", "Favourite", "Model probability", "Market probability", "Edge", "bookmaker", "observed_at"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Model probability": st.column_config.NumberColumn(format="percent"),
                "Market probability": st.column_config.NumberColumn(format="percent"),
                "Edge": st.column_config.NumberColumn(format="percent"),
            },
        )

with odds_tab:
    movement = odds_movement()
    if movement.empty:
        st.info("Opening/current line tracking begins after at least two archived snapshots.")
    else:
        movement["Decimal move"] = movement["current_decimal"] - movement["opening_decimal"]
        st.dataframe(movement, width="stretch", hide_index=True)

with props_tab:
    fixtures, _ = load_upcoming()
    odds = latest_odds()
    st.warning(
        "Set totals, handicaps, and correct scores are research-only. The calculations below expose marginal "
        "probabilities, but placement remains blocked until exact-format settlement and point-level validation pass."
    )
    if fixtures.empty:
        st.info("No upcoming fixtures are available for prop research.")
    else:
        labels = fixtures.apply(lambda r: f"{r.get('Home', '')} vs {r.get('Away', '')} · {r.get('Tournament', '')}", axis=1)
        selected_label = st.selectbox("Fixture", labels.tolist(), key="prop_fixture")
        row = fixtures.iloc[labels.tolist().index(selected_label)]
        home_probability = float(row.get("Home Win Probability", 0.5) or 0.5)
        set_probability = 0.5 + 0.72 * (home_probability - 0.5)
        distribution = set_score_distribution(set_probability, 3)
        favorite_home = home_probability >= 0.5
        favorite_sweep = distribution["3-0"] if favorite_home else distribution["0-3"]
        favorite_minus_15 = sum(
            probability
            for score, probability in distribution.items()
            if ((int(score[0]) - int(score[-1])) >= 2 if favorite_home else (int(score[-1]) - int(score[0])) >= 2)
        )
        over_35 = sum(probability for score, probability in distribution.items() if sum(map(int, score.split("-"))) >= 4)
        prop_rows = pd.DataFrame(
            [
                {"Research market": "Favorite sweep 3–0", "Model probability": favorite_sweep},
                {"Research market": "Favorite -1.5 sets", "Model probability": favorite_minus_15},
                {"Research market": "Over 3.5 sets", "Model probability": over_35},
            ]
        )
        st.dataframe(
            prop_rows,
            width="stretch",
            hide_index=True,
            column_config={"Model probability": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
        )
        event_prices = odds[odds["event_key"] == row.get("Event Key")] if not odds.empty else pd.DataFrame()
        prop_prices = event_prices[~event_prices["market"].str.casefold().isin({"match_winner", "h2h", "moneyline"})] if not event_prices.empty else pd.DataFrame()
        if prop_prices.empty:
            st.caption("No archived DraftKings/non-moneyline prop snapshots are available for this event.")
        else:
            st.dataframe(prop_prices, width="stretch", hide_index=True)

with parlay_tab:
    st.error(
        "Parlay construction is disabled. Marginal match calibration does not establish joint calibration, "
        "and the audit requires that evidence before combining legs."
    )
    st.text_input("Leg 1", disabled=True, placeholder="Locked until joint calibration gate passes")
    st.text_input("Leg 2", disabled=True, placeholder="Locked until joint calibration gate passes")
    st.button("Build parlay", disabled=True)

with roi_tab:
    roi = db.paper_roi_by_day()
    if roi.empty:
        st.info("No settled paper bets exist yet. The calendar will activate after settlement records are archived.")
    else:
        roi["month"] = roi["day"].str[:7]
        roi["day_of_month"] = pd.to_datetime(roi["day"]).dt.day
        fig = px.bar(roi, x="day", y="profit", color="profit", color_continuous_scale="RdYlGn")
        st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        c1.metric("Best day", roi.loc[roi["profit"].idxmax(), "day"], f"{roi['profit'].max():+.2f}u")
        c2.metric("Worst day", roi.loc[roi["profit"].idxmin(), "day"], f"{roi['profit'].min():+.2f}u")

add_betting_oracle_footer()
