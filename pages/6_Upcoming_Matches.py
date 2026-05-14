"""
Upcoming Matches — betting review dashboard.

Reads pre-computed fixture predictions from:
    processed/upcoming_enriched.json

That file is generated nightly by:
    python scripts/tt_precompute.py

Which should be run after scraping fresh fixtures:
    python scripts/tt_scraper.py sofa --start DATE --end DATE+3 --no-stats
    python scripts/tt_precompute.py
"""

from __future__ import annotations

import json
from datetime import date as _date, timedelta as _td
from pathlib import Path

import pandas as pd
import streamlit as st

st.title("📅 Upcoming Matches")

ENRICHED_PATH = Path(__file__).parent.parent / "processed" / "upcoming_enriched.json"

# ── Load precomputed data ──────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_enriched() -> tuple[pd.DataFrame, str]:
    """Load the precomputed enriched fixtures. Returns (df, generated_at)."""
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
    return pd.DataFrame(fixtures), generated_at


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
    st.caption(f"Last updated: {generated_at[:16].replace('T', ' ')} UTC")

# ── Sidebar / filter controls ──────────────────────────────────────────────────

all_dates       = sorted(df_all["_date"].unique())
all_tournaments = sorted(df_all["Tournament"].unique())

with st.sidebar:
    st.header("Filters")
    sel_dates = st.multiselect(
        "Date", all_dates,
        default=all_dates,
        key="up_dates",
    )
    sel_tourneys = st.multiselect(
        "Tournament", all_tournaments,
        key="up_tourneys",
    )
    min_confidence = st.selectbox(
        "Minimum confidence",
        ["All", "Medium or higher", "High only"],
        index=0,
        key="up_conf",
    )

df = df_all[df_all["_date"].isin(sel_dates)]
if sel_tourneys:
    df = df[df["Tournament"].isin(sel_tourneys)]

if min_confidence == "High only":
    df = df[df["_conf_label"] == "High"]
elif min_confidence == "Medium or higher":
    df = df[df["_conf_label"].isin(["High", "Medium"])]

if df.empty:
    st.info("No matches match the current filters.")
    st.stop()

# ── Summary metrics ────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns(3)
c1.metric("Fixtures",    len(df))
c2.metric("Tournaments", df["Tournament"].nunique())
c3.metric("Days",        df["_date"].nunique())

st.divider()

# ── Table (grouped by day) ─────────────────────────────────────────────────────

display_cols = [
    "Time", "Tournament", "Home", "Away",
    "Home Rank", "Away Rank",
    "Favourite", "Win %", "Confidence",
    "H2H (home W-L)", "Home Recent", "Away Recent",
    "Home Overall", "Away Overall",
]

today_str = _date.today().isoformat()

for day_str in sorted(df["_date"].unique()):
    day_df = df[df["_date"] == day_str][display_cols].reset_index(drop=True)
    label  = "Today" if day_str == today_str else day_str
    st.subheader(f"📆 {label} — {len(day_df)} fixture{'s' if len(day_df) != 1 else ''}")
    st.dataframe(
        day_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Win %":      st.column_config.TextColumn("Win %",      width="small"),
            "Confidence": st.column_config.TextColumn("Confidence", width="small"),
            "Home Rank":  st.column_config.TextColumn("Rank",       width="small"),
            "Away Rank":  st.column_config.TextColumn("Rank",       width="small"),
        },
    )