from __future__ import annotations

import streamlit as st
import plotly.express as px

import db
from frontier_data import load_backtest

st.title("📈 Backtesting")
st.caption("Leakage-safe event-time replay: every forecast is emitted before that match updates ratings or form")

window_days = st.slider("Backtest window (days)", min_value=30, max_value=720, value=180, step=30)

with st.spinner("Running backtest..."):
    by_bucket, summary = db.backtest_prediction_report(window_days=window_days)

if by_bucket.empty:
    st.warning("No ended matches available for the selected window.")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Matches", f"{summary['matches']:,}")
c2.metric("Accuracy", f"{summary['accuracy'] * 100:.1f}%")
c3.metric("Brier", f"{summary['brier']:.4f}")
c4.metric("Log loss", f"{summary['log_loss']:.4f}")
c5.metric("Coverage", f"{summary['coverage']:.1%}")
st.caption(
    f"{summary['method']} · evaluation begins {summary['evaluation_start']} · "
    f"calibration error (ECE): {summary['ece']:.4f} · quarantined rows excluded: {summary['quarantined_rows_excluded']:,}"
)
st.warning(
    "This is a model replay, not a betting backtest. No historical price snapshots exist for most rows, "
    "so ROI, CLV, and claims about the current deployed model remain unavailable."
)

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Accuracy by confidence")
    fig_acc = px.bar(
        by_bucket,
        x="bucket",
        y="accuracy",
        labels={"bucket": "Confidence", "accuracy": "Accuracy"},
        text=by_bucket["accuracy"].map(lambda x: f"{x*100:.1f}%"),
    )
    fig_acc.update_yaxes(range=[0, 1])
    fig_acc.update_layout(margin=dict(t=10, b=10), height=320)
    st.plotly_chart(fig_acc, width="stretch")

with right:
    st.subheader("Brier score by confidence")
    fig_brier = px.bar(
        by_bucket,
        x="bucket",
        y="brier",
        labels={"bucket": "Confidence", "brier": "Brier"},
        text=by_bucket["brier"].map(lambda x: f"{x:.4f}"),
    )
    fig_brier.update_layout(margin=dict(t=10, b=10), height=320)
    st.plotly_chart(fig_brier, width="stretch")

st.subheader("Bucket details")
view = by_bucket.copy()
view["accuracy"] = (view["accuracy"] * 100).round(1).astype(str) + "%"
view["brier"] = view["brier"].round(4)
view["log_loss"] = view["log_loss"].round(4)
view["coverage"] = (view["coverage"] * 100).round(1).astype(str) + "%"
st.dataframe(view.rename(columns={"bucket": "Confidence"}), width="stretch", hide_index=True)

report = load_backtest()
if report:
    st.divider()
    tier_tab, source_tab, tournament_tab, candidate_tab = st.tabs(
        ["Tournament tiers", "Sources", "Top tournaments", "Model candidates"]
    )

    def metric_frame(payload: dict) -> "pd.DataFrame":
        import pandas as pd

        rows = []
        for label, values in payload.items():
            if not isinstance(values, dict):
                continue
            rows.append({"Segment": label, **values})
        return pd.DataFrame(rows)

    with tier_tab:
        st.dataframe(metric_frame(report.get("by_tournament_tier", {})), width="stretch", hide_index=True)
        st.caption("Tier 1 major rows may be absent in the selected source/time block; absence is reported, not imputed.")
    with source_tab:
        st.dataframe(metric_frame(report.get("by_source", {})), width="stretch", hide_index=True)
    with tournament_tab:
        st.dataframe(metric_frame(report.get("by_top_tournament", {})), width="stretch", hide_index=True)
        robust = report.get("robustness_excluding_tier4", {})
        if robust:
            st.json({"Robustness after excluding Tier 4": robust})
    with candidate_tab:
        comparison = report.get("candidate_comparison", {})
        st.dataframe(metric_frame(comparison), width="stretch", hide_index=True)
        st.caption(
            "Candidate selection uses a chronological outer holdout, participant-pair grouped inner folds, "
            "and a separate deterministic tournament holdout."
        )
