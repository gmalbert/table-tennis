"""
Recent Matches — reads directly from data/flashscore/ JSON files
(no DB needed; always shows the freshest data from the weekly GH Action).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

st.title("📡 Recent Matches")
st.caption("Live data from Flashscore — last 7 days")

FLASH_DIR = Path(__file__).parent.parent / "data" / "flashscore"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_sets(sets: list[dict]) -> str:
    return "  ".join(f"{s.get('home','')}:{s.get('away','')}" for s in sets)


def load_day(day_dir: Path) -> list[dict]:
    json_file = day_dir / "matches.json"
    if not json_file.exists():
        return []
    try:
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("matches", [])
    except Exception:
        return []


# ── Controls ──────────────────────────────────────────────────────────────────

today     = date.today()
days_back = st.slider("Days to show", min_value=1, max_value=7, value=7)

days = [today - timedelta(days=i) for i in range(days_back)]
days_with_data = [d for d in days if (FLASH_DIR / d.isoformat()).exists()]

if not days_with_data:
    st.warning(
        "No Flashscore data found in `data/flashscore/`. "
        "Run the scraper: `python scripts/tt_scraper.py flash --start <date> --end <date>`"
    )
    st.stop()

# ── Aggregate ─────────────────────────────────────────────────────────────────
all_rows: list[dict] = []
for d in days_with_data:
    for m in load_day(FLASH_DIR / d.isoformat()):
        if not m.get("score_home") and not m.get("score_away"):
            continue  # skip unplayed / no score recorded
        all_rows.append({
            "Date":       d.isoformat(),
            "Tournament": m.get("tournament", ""),
            "Home":       m.get("home_player", ""),
            "Away":       m.get("away_player", ""),
            "Score":      f"{m.get('score_home','')}–{m.get('score_away','')}",
            "Sets":       _fmt_sets(m.get("sets", [])),
        })

if not all_rows:
    st.info("No completed matches found in the selected range.")
    st.stop()

df = pd.DataFrame(all_rows)

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
c1.metric("Days loaded",   len(days_with_data))
c2.metric("Matches",       len(df))
c3.metric("Tournaments",   df["Tournament"].nunique())

# ── Filters ───────────────────────────────────────────────────────────────────
with st.expander("Filters"):
    day_filter   = st.multiselect("Date",        sorted(df["Date"].unique(), reverse=True),
                                  default=sorted(df["Date"].unique(), reverse=True))
    tourn_filter = st.multiselect("Tournament",  sorted(df["Tournament"].unique()))

filtered = df.copy()
if day_filter:
    filtered = filtered[filtered["Date"].isin(day_filter)]
if tourn_filter:
    filtered = filtered[filtered["Tournament"].isin(tourn_filter)]

st.divider()

# ── Display grouped by day ────────────────────────────────────────────────────
for day_str in sorted(filtered["Date"].unique(), reverse=True):
    day_df = filtered[filtered["Date"] == day_str]
    st.subheader(day_str)
    st.dataframe(
        day_df[["Tournament", "Home", "Away", "Score", "Sets"]].reset_index(drop=True),
        width="stretch",
        hide_index=True,
    )


def _fmt_sets(sets: list[dict]) -> str:
    return "  ".join(f"{s.get('home','')}:{s.get('away','')}" for s in sets)
