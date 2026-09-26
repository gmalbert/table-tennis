import os
import streamlit as st
import plotly.express as px

import db
from footer import add_betting_oracle_footer
from frontier_data import current_release_gates, feed_age_minutes, load_upcoming

# ── Called ONCE — sub-pages must NOT call set_page_config ─────────────────────
st.set_page_config(
    page_title="Pong Odds",
    page_icon="🏓",
    layout="wide",
)


def home_page():
    logo_path = os.path.join(os.path.dirname(__file__), "data_files", "logo.png")
    if os.path.exists(logo_path):
        st.image(logo_path, width=160)
    else:
        st.title("🏓 Pong Odds")
    st.caption("Auditable table tennis forecasting, rankings, match context, and paper betting research")

    # Always check release freshness so cloud instances with an existing
    # stale DB can pull the latest published snapshot.
    db.ensure_db()
    # ── Top 15 upcoming bets ─────────────────────────────────────────
    st.subheader("🔥 Match Day — top upcoming forecasts")
    st.caption("Paper-only until the release gates are satisfied; probabilities are not prices.")
    c1, c2, c3 = st.columns(3)
    min_conf = c1.selectbox("Min confidence", ["Low", "Medium", "High"], index=0, key="home_min_conf")
    min_cov = c2.selectbox("Min coverage", ["Low", "Medium", "High"], index=0, key="home_min_cov")
    min_sample = c3.slider("Min sample size", min_value=0, max_value=200, value=0, step=5, key="home_min_sample")

    bets = db.top_upcoming_bets(
        n=15,
        min_confidence=min_conf,
        min_coverage_tier=min_cov,
        min_sample_size=min_sample,
    )
    if bets.empty:
        st.info("No upcoming fixtures available. Run the nightly pre-compute script.")
    else:
        _, generated_at = load_upcoming()
        age = feed_age_minutes(generated_at)
        if age is not None:
            st.caption(f"Feed age: {age:.0f} minutes · live updates require a measured point-level feed")
        best = bets.iloc[0]
        st.success(
            f"Best paper forecast: **{best['Favorite']}** · {best['Win %']} · "
            f"{best['Tournament']} · {best['Why']}"
        )
        st.dataframe(bets, width="stretch", hide_index=True)

    audit, gates = current_release_gates()
    st.caption(
        f"Release gate: {gates['match_winner']['mode']} · "
        f"{audit['frozen_forecasts']:,}/1,000 frozen forecasts · "
        f"{audit['settled_bets']:,}/500 settled paper bets"
    )

    st.divider()
    # ── Summary metrics ───────────────────────────────────────────────────────
    stats = db.summary_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matches", f"{stats['matches']:,}")
    c2.metric("Players / Teams", f"{stats['players']:,}")
    c3.metric("Tournaments", f"{stats['tournaments']:,}")
    c4.metric("Date range", f"{stats['min_date'][:4]} – {stats['max_date'][:4]}")

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Matches per year")
        df_year = db.matches_per_year()
        fig = px.bar(df_year, x="year", y="matches", labels={"year": "", "matches": "Matches"})
        fig.update_xaxes(dtick=1, tickformat="d")
        fig.update_layout(margin=dict(t=10, b=10), height=320)
        st.plotly_chart(fig, width="stretch")

    with right:
        st.subheader("Top 15 tournaments")
        df_t = db.top_tournaments(15)
        fig2 = px.bar(
            df_t.sort_values("matches"),
            x="matches", y="tournament_name",
            orientation="h",
            labels={"matches": "Matches", "tournament_name": ""},
        )
        fig2.update_yaxes(automargin=True)
        fig2.update_layout(margin=dict(t=10, b=10, l=10), height=400)
        st.plotly_chart(fig2, width="stretch")

    add_betting_oracle_footer()


# ── Sidebar navigation (Streamlit 1.45+) ──────────────────────────────────────
pg = st.navigation(
    [
        st.Page(home_page,                     title="Home",             icon="🏓", default=True),
        st.Page("pages/6_Upcoming_Matches.py", title="Upcoming Matches", icon="📅"),
        st.Page("pages/1_Player_Stats.py",     title="Player Stats",     icon="👤"),
        st.Page("pages/2_Head_to_Head.py",     title="Head to Head",     icon="⚔️"),
        st.Page("pages/3_Tournaments.py",      title="Tournaments",      icon="🏆"),
        st.Page("pages/4_Predict.py",          title="Predict",          icon="🔮"),
        st.Page("pages/5_Recent_Matches.py",   title="Recent Matches",   icon="📡"),
        st.Page("pages/7_Backtesting.py",      title="Backtesting",      icon="📈"),
        st.Page("pages/8_World_Rankings.py",  title="World Rankings",   icon="🌍"),
        st.Page("pages/9_Betting_Tools.py",   title="Betting Tools",    icon="🧰"),
        st.Page("pages/10_Tournament_Brackets.py", title="Brackets",    icon="🧩"),
        st.Page("pages/11_Model_Lab.py",      title="Model Lab",        icon="🧪"),
        st.Page("pages/12_Data_Quality.py",   title="Data Quality",     icon="🛡️"),
    ],
    position="sidebar",
)

# ── Sidebar logo ───────────────────────────────────────────────────────────────
logo_path = os.path.join(os.path.dirname(__file__), "data_files", "logo.png")
if os.path.exists(logo_path) and pg.title != "Home":
    with st.sidebar:
        st.image(logo_path, width=160)

pg.run()
