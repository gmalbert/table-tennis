from __future__ import annotations

import streamlit as st
import plotly.express as px

import db

st.title("📈 Backtesting")
st.caption("Evaluate prediction quality by confidence bucket on recent historical matches")

window_days = st.slider("Backtest window (days)", min_value=30, max_value=720, value=180, step=30)

with st.spinner("Running backtest..."):
    by_bucket, summary = db.backtest_prediction_report(window_days=window_days)

if by_bucket.empty:
    st.warning("No ended matches available for the selected window.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Matches", f"{summary['matches']:,}")
c2.metric("Accuracy", f"{summary['accuracy'] * 100:.1f}%")
c3.metric("Brier", f"{summary['brier']:.4f}")

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
st.dataframe(view.rename(columns={"bucket": "Confidence"}), width="stretch", hide_index=True)
