from __future__ import annotations

import os

import pandas as pd
import streamlit as st

import db
from footer import add_betting_oracle_footer
from frontier_data import current_release_gates, feed_age_minutes, load_upcoming
from models.audit_store import submit_correction
from models.frontier_model import source_reliability


st.title("🛡️ Data Quality & Operations")
st.caption("Source lineage, anomaly quarantine, feed latency, correction requests, and automation readiness")

overview_tab, source_tab, correction_tab, automation_tab = st.tabs(
    ["Integrity overview", "Source reliability", "Corrections", "Automation"]
)

with overview_tab:
    summary, gates = current_release_gates()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frozen forecasts", f"{summary['frozen_forecasts']:,}")
    c2.metric("Settled paper bets", f"{summary['settled_bets']:,}")
    c3.metric("Open flags", f"{summary['open_quality_flags']:,}")
    c4.metric("Positive CLV", "Yes" if summary.get("positive_clv") else "Not established")
    st.caption(
        f"Point events: {summary.get('point_events', 0):,} · "
        f"latency coverage: {summary.get('point_latency_coverage', 0.0):.1%} (live gate requires 1,000 / 95%)"
    )
    if db.db_ready():
        quality = db.data_quality_overview().iloc[0]
        st.dataframe(
            pd.DataFrame(
                [
                    {"Check": "Missing participant identity", "Rows": int(quality["missing_identity"] or 0), "Action": "Quarantine"},
                    {"Check": "Home/away identity collision", "Rows": int(quality["identity_collisions"] or 0), "Action": "Quarantine"},
                    {"Check": "Walkover/retired/cancelled", "Rows": int(quality["nonstandard"] or 0), "Action": "Exclude from standard settlement"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    fixtures, generated_at = load_upcoming()
    age = feed_age_minutes(generated_at)
    if age is None:
        st.warning("Upcoming-feed timestamp is unavailable.")
    else:
        status = "Fresh" if age <= 180 else "Stale"
        st.metric("Upcoming feed latency", f"{age:.0f} minutes", status)
    st.error("Point/rally feed: not connected · live probability is therefore blocked")

with source_tab:
    rows = []
    for source, coverage in [
        ("ittf", "Official results, rankings, brackets"),
        ("sofascore", "Recent/live events and set scores"),
        ("flashscore", "Recent scores, rankings, H2H"),
        ("odds-api.io", "Timestamped market prices"),
        ("oddsportal", "Documented research source; connector not configured"),
        ("betexplorer", "Documented cross-check source; connector not configured"),
    ]:
        reliability = source_reliability(source)
        rows.append({"Source": source, "Reliability": reliability["label"], "Score": reliability["score"], "Coverage": coverage})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("Unknown or low-integrity competitions are quarantined or cause model abstention; values are never silently corrected.")

with correction_tab:
    st.write("Submit an alias, duplicate-event, or metadata correction for review. This records a request; it does not rewrite source history.")
    with st.form("correction_form"):
        entity_type = st.selectbox("Entity type", ["player_identity", "match", "tournament", "odds_snapshot"])
        entity_key = st.text_input("Entity key")
        requested_change = st.text_area("Requested correction")
        evidence_url = st.text_input("Evidence URL (optional)")
        submitted = st.form_submit_button("Submit correction")
    if submitted:
        if not entity_key.strip() or not requested_change.strip():
            st.error("Entity key and requested correction are required.")
        else:
            correction_id = submit_correction(entity_type, entity_key.strip(), requested_change.strip(), evidence_url.strip())
            st.success(f"Correction request recorded: {correction_id}")

with automation_tab:
    config = pd.DataFrame(
        [
            {"Automation": "Nightly results + predictions", "Schedule": "Daily", "Configured": True},
            {"Automation": "ITTF rankings sync", "Schedule": "Monday", "Configured": True},
            {"Automation": "Odds snapshots", "Schedule": "Every 2 hours", "Configured": bool(os.getenv("ODDS_API_IO_KEY"))},
            {"Automation": "Discord paper pick", "Schedule": "After nightly refresh", "Configured": bool(os.getenv("DISCORD_WEBHOOK_URL"))},
            {"Automation": "Event-week email webhook", "Schedule": "Monday", "Configured": bool(os.getenv("EMAIL_WEBHOOK_URL"))},
        ]
    )
    st.dataframe(config, width="stretch", hide_index=True)
    st.caption("Configured means the current process can see the required credential; secret values are never displayed.")

add_betting_oracle_footer()
