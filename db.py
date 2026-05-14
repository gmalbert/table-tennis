"""
Shared database helper for the Streamlit app.

All pages import from here so caching is consistent and the connection
is a singleton (check_same_thread=False is safe for read-only queries).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "processed" / "tt.db"

# GitHub Releases URL for the database file.
# Update the tag (db-latest) if you publish a new release.
DB_RELEASE_URL = (
    "https://github.com/gmalbert/table-tennis/releases/download/db-latest/tt.db"
)

ENDED = "Ended"


# ── Download ──────────────────────────────────────────────────────────────────

def ensure_db() -> None:
    """Download tt.db from GitHub Releases if it is not present locally.

    Shows a Streamlit progress bar while downloading so the user knows
    the app is working. Calls st.stop() on failure to abort the page.
    """
    if DB_PATH.exists():
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    import requests

    st.info("Database not cached — downloading (~1.4 GB). This only happens on the first run after a new deployment.", icon="⬇️")
    progress_bar = st.progress(0.0, text="Connecting…")
    tmp_path = DB_PATH.with_suffix(".tmp")

    try:
        with requests.get(DB_RELEASE_URL, stream=True, timeout=600) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total
                        progress_bar.progress(
                            pct,
                            text=f"Downloading tt.db… {downloaded / 1e9:.2f} / {total / 1e9:.2f} GB",
                        )
        tmp_path.rename(DB_PATH)
        progress_bar.progress(1.0, text="Download complete!")
        st.rerun()
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        st.error(f"Failed to download database: {exc}")
        st.stop()


# ── Connection ────────────────────────────────────────────────────────────────

@st.cache_resource
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")   # 64 MB page cache
    return conn


def db_ready() -> bool:
    return DB_PATH.exists()


# ── Home page stats ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def summary_stats() -> dict:
    conn = get_conn()
    total  = pd.read_sql(f"SELECT COUNT(*) n FROM matches WHERE status_description='{ENDED}'", conn).iloc[0, 0]
    total_p = pd.read_sql("SELECT COUNT(*) n FROM players", conn).iloc[0, 0]
    total_t = pd.read_sql(f"SELECT COUNT(DISTINCT tournament_name) n FROM matches WHERE status_description='{ENDED}'", conn).iloc[0, 0]
    dr = pd.read_sql("SELECT MIN(date) mn, MAX(date) mx FROM matches", conn).iloc[0]
    return dict(matches=int(total), players=int(total_p), tournaments=int(total_t),
                min_date=dr["mn"], max_date=dr["mx"])


@st.cache_data(ttl=3600)
def matches_per_year() -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT substr(date,1,4) year, COUNT(*) matches FROM matches "
        f"WHERE status_description='{ENDED}' GROUP BY year ORDER BY year",
        get_conn(),
    )


@st.cache_data(ttl=3600)
def top_tournaments(n: int = 15) -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT tournament_name, COUNT(*) matches FROM matches "
        f"WHERE status_description='{ENDED}' "
        f"GROUP BY tournament_name ORDER BY matches DESC LIMIT {n}",
        get_conn(),
    )


# ── Player helpers ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def all_player_names() -> pd.DataFrame:
    """Returns id, name, slug sorted by name."""
    return pd.read_sql("SELECT id, name, slug FROM players ORDER BY name", get_conn())


@st.cache_data(ttl=3600)
def player_matches(slug: str) -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT * FROM matches WHERE (home_slug=? OR away_slug=?) "
        f"AND status_description='{ENDED}' ORDER BY date DESC",
        get_conn(), params=[slug, slug],
    )


@st.cache_data(ttl=3600)
def player_wins_by_year(slug: str) -> pd.DataFrame:
    """Returns year, wins, losses for the player."""
    df = player_matches(slug)
    if df.empty:
        return pd.DataFrame(columns=["year", "wins", "losses"])
    df["year"] = df["date"].str[:4]
    df["won"]  = ((df["home_slug"] == slug) & (df["winner"] == "home")) | \
                 ((df["away_slug"] == slug) & (df["winner"] == "away"))
    grouped = df.groupby("year")["won"].agg(wins="sum", losses=lambda x: (~x).sum()).reset_index()
    return grouped


def player_record(df: pd.DataFrame, slug: str) -> tuple[int, int]:
    """Given a matches DataFrame, return (wins, losses) for slug."""
    wins = (
        ((df["home_slug"] == slug) & (df["winner"] == "home")) |
        ((df["away_slug"] == slug) & (df["winner"] == "away"))
    ).sum()
    return int(wins), int(len(df) - wins)


# ── H2H helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def h2h_matches(slug1: str, slug2: str) -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT * FROM matches "
        f"WHERE ((home_slug=? AND away_slug=?) OR (home_slug=? AND away_slug=?)) "
        f"AND status_description='{ENDED}' ORDER BY date DESC",
        get_conn(), params=[slug1, slug2, slug2, slug1],
    )


# ── Tournament helpers ────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def all_tournament_names() -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT tournament_name, COUNT(*) match_count, "
        f"MIN(date) first_date, MAX(date) last_date "
        f"FROM matches WHERE status_description='{ENDED}' "
        f"GROUP BY tournament_name ORDER BY match_count DESC",
        get_conn(),
    )


@st.cache_data(ttl=3600)
def tournament_matches(tournament_name: str) -> pd.DataFrame:
    return pd.read_sql(
        f"SELECT * FROM matches WHERE tournament_name=? "
        f"AND status_description='{ENDED}' ORDER BY date DESC",
        get_conn(), params=[tournament_name],
    )


# ── Prediction helpers ────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def overall_win_rate(slug: str) -> float:
    """Fraction of ended matches the player won. Returns 0.5 if no data."""
    df = player_matches(slug)
    if df.empty:
        return 0.5
    w, l = player_record(df, slug)
    return w / (w + l) if (w + l) > 0 else 0.5


@st.cache_data(ttl=3600)
def recent_win_rate(slug: str, last_n: int = 20) -> float:
    df = player_matches(slug).head(last_n)
    if df.empty:
        return 0.5
    w, l = player_record(df, slug)
    return w / (w + l) if (w + l) > 0 else 0.5
