"""
Upcoming Matches - betting review dashboard.

Reads pre-computed fixture predictions from:
    processed/upcoming_enriched.json

That file is generated nightly by:
    python scripts/tt_precompute.py
"""

from __future__ import annotations

import json
from datetime import date as _date, datetime, timedelta as _td, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.title("\U0001f4c5 Upcoming Matches")

ENRICHED_PATH = Path(__file__).parent.parent / "processed" / "upcoming_enriched.json"
ET = ZoneInfo("America/New_York")

# -- Load precomputed data -----------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def load_enriched() -> tuple[pd.DataFrame, str]:
    if not ENRICHED_PATH.exists():
        return pd.DataFrame(), ""
    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return pd.DataFrame(), ""
    fixtures = data.get("fixtures", [])
    generated_at = data.get("generated_at", "")
    if not fixtures:
        return pd.DataFrame(), generated_at

    df = pd.DataFrame(fixtures)

    # Convert UTC times to US/Eastern; rebuild _date from ET datetime so
    # late-UTC matches land on the right ET calendar day.
    def to_et(row) -> tuple[str, str]:
        raw_time = row.get("Time", "")
        raw_date = row.get("_date", "")
        if not raw_time or not raw_date:
            return raw_date, raw_time
        try:
            dt_utc = datetime.strptime(
                f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
            dt_et = dt_utc.astimezone(ET)
            return dt_et.strftime("%Y-%m-%d"), dt_et.strftime("%H:%M")
        except Exception:
            return raw_date, raw_time

    et_cols = df.apply(to_et, axis=1, result_type="expand")
    df["_date"] = et_cols[0]
    df["Time"]  = et_cols[1]

    # Drop fixtures whose ET calendar date is in the past
    today_et = datetime.now(ET).date().isoformat()
    df = df[df["_date"] >= today_et]

    return df, generated_at


df_all, generated_at = load_enriched()

if df_all.empty:
    _today = _date.today()
    _end   = _today + _td(days=3)
    st.warning(
        "No upcoming fixtures found. Run the nightly pre-compute script to populate this page:\n\n"
        f"```\n"
        f"python scripts/tt_scraper.py sofa --start {_today} --end {_end} --no-stats\n"
        f"python scripts/tt_precompute.py\n"
        f"```"
    )
    st.stop()

if generated_at:
    ts = generated_at[:16].replace("T", " ")
    st.caption(f"Last updated: {ts} UTC")

# -- Sidebar filters -----------------------------------------------------------

all_dates = sorted(df_all["_date"].unique())

with st.sidebar:
    st.header("Filters")
    min_confidence = st.radio(
        "Confidence",
        ["All", "Medium +", "High only"],
        index=0,
        key="up_conf",
    )
    tournament_search = st.text_input(
        "Tournament search",
        placeholder="e.g. ETTU, WTT...",
        key="up_tsearch",
    )

df = df_all.copy()
if min_confidence == "High only":
    df = df[df["_conf_label"] == "High"]
elif min_confidence == "Medium +":
    df = df[df["_conf_label"].isin(["High", "Medium"])]
if tournament_search:
    df = df[df["Tournament"].str.contains(tournament_search, case=False, na=False)]

if df.empty:
    st.info("No matches match the current filters.")
    st.stop()

# -- Summary metrics -----------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fixtures",        len(df))
c2.metric("Tournaments",     df["Tournament"].nunique())
c3.metric("Days",            df["_date"].nunique())
c4.metric("High confidence", (df["_conf_label"] == "High").sum())

st.divider()

# -- Layout: tabs by date, then expanders by tournament -----------------------
#
# Each tournament is collapsed by default; those with >= 1 high-confidence
# pick are auto-expanded so the interesting matches surface immediately.

today_str     = _date.today().isoformat()
dates_present = [d for d in all_dates if d in df["_date"].values]
tab_labels    = [
    ("\U0001f5d3 Today" if d == today_str else f"\U0001f5d3 {d}")
    for d in dates_present
]

display_cols = [
    "Time ET", "Home", "Away",
    "Favorite", "Win %", "Confidence",
    "H2H (home W-L)", "Home Recent", "Away Recent",
    "Home Overall", "Away Overall",
]

tabs = st.tabs(tab_labels)

for tab, day_str in zip(tabs, dates_present):
    day_df = df[df["_date"] == day_str].copy()
    day_df = day_df.rename(columns={"Time": "Time ET", "Favourite": "Favorite"})

    with tab:
        total = len(day_df)
        h_ct  = (day_df["_conf_label"] == "High").sum()
        m_ct  = (day_df["_conf_label"] == "Medium").sum()
        st.caption(
            f"{total} fixture{'s' if total != 1 else ''} "
            f"\u00b7 \U0001f7e2 {h_ct} high "
            f"\u00b7 \U0001f7e1 {m_ct} medium"
        )

        # Most-matches tournaments first
        tourney_counts = (
            day_df.groupby("Tournament")
            .size()
            .sort_values(ascending=False)
        )

        for tourney, count in tourney_counts.items():
            mask     = day_df["Tournament"] == tourney
            t_df     = day_df[mask][display_cols].reset_index(drop=True)
            t_high   = int((day_df[mask]["_conf_label"] == "High").sum())
            t_medium = int((day_df[mask]["_conf_label"] == "Medium").sum())

            badges = ""
            if t_high:
                badges += f" \u00b7 \U0001f7e2 {t_high}"
            if t_medium:
                badges += f" \u00b7 \U0001f7e1 {t_medium}"

            suffix = "matches" if count != 1 else "match"
            label  = f"**{tourney}** \u2014 {count} {suffix}{badges}"

            with st.expander(label, expanded=(t_high > 0)):
                st.dataframe(
                    t_df,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Time ET":    st.column_config.TextColumn("Time (ET)", width="small"),
                        "Win %":      st.column_config.TextColumn("Win %",     width="small"),
                        "Confidence": st.column_config.TextColumn("Conf.",     width="small"),
                    },
                )
