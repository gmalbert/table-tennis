"""
Shared database helper for the Streamlit app.

All pages import from here so caching is consistent and the connection
is a singleton (check_same_thread=False is safe for read-only queries).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "processed" / "tt.db"
# Stamp file: small JSON that records the last API-check time and the
# release's published_at so we can avoid re-downloading when nothing changed.
STAMP_PATH = DB_PATH.with_suffix(".stamp")

GITHUB_REPO = "gmalbert/table-tennis"
DB_RELEASE_TAG = "db-latest"
DB_RELEASE_URL = (
    f"https://github.com/{GITHUB_REPO}/releases/download/{DB_RELEASE_TAG}/tt.db"
)
# How often (seconds) the app calls the GitHub API to check for a newer release.
DB_CHECK_INTERVAL = 12 * 3600  # 12 hours

ENDED = "Ended"


# ── Download helpers ──────────────────────────────────────────────────────────

def _read_stamp() -> dict:
    """Return the stamp dict or an empty dict if missing / unreadable."""
    import json
    try:
        return json.loads(STAMP_PATH.read_text())
    except Exception:
        return {}


def _write_stamp(last_checked: str, release_published_at: str) -> None:
    import json
    STAMP_PATH.write_text(
        json.dumps({"last_checked": last_checked, "release_published_at": release_published_at})
    )


def _fetch_release_published_at() -> str | None:
    """Call the GitHub API and return the release's published_at ISO string, or None on error."""
    import requests
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{DB_RELEASE_TAG}"
    try:
        r = requests.get(url, timeout=15, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        return r.json().get("published_at")
    except Exception:
        return None


def _db_needs_update() -> bool:
    """Return True if the DB is missing or a newer release is available.

    Calls the GitHub API at most once every DB_CHECK_INTERVAL seconds.
    """
    from datetime import datetime, timezone

    if not DB_PATH.exists():
        return True

    stamp = _read_stamp()
    now = datetime.now(tz=timezone.utc)

    # Skip API call if we checked recently.
    last_checked_str = stamp.get("last_checked")
    if last_checked_str:
        last_checked = datetime.fromisoformat(last_checked_str)
        if (now - last_checked).total_seconds() < DB_CHECK_INTERVAL:
            return False

    # Hit the API.
    remote_ts = _fetch_release_published_at()
    if remote_ts is None:
        # Network error — don't force a re-download.
        return False

    _write_stamp(last_checked=now.isoformat(), release_published_at=remote_ts)

    local_ts = stamp.get("release_published_at")
    if local_ts is None:
        # No stamp yet but file exists — treat as stale so stamp gets written.
        return True

    return remote_ts > local_ts


def _download_db() -> None:
    """Stream tt.db from GitHub Releases with a Streamlit progress bar."""
    import requests

    st.info(
        "Downloading database (~1.4 GB) — this only happens when a new release is published.",
        icon="⬇️",
    )
    progress_bar = st.progress(0.0, text="Connecting…")
    tmp_path = DB_PATH.with_name(f"{DB_PATH.name}.tmp")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Remove a stale temp file from a previous interrupted download.
    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

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
        # On Windows, rename() cannot overwrite an existing file.
        tmp_path.replace(DB_PATH)
        progress_bar.progress(1.0, text="Download complete!")
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        st.error(f"Failed to download database: {exc}")
        st.stop()


def ensure_db() -> None:
    """Ensure tt.db is present and up to date.

    - If missing: downloads immediately.
    - If present: checks the GitHub Releases API at most once every
      DB_CHECK_INTERVAL seconds and re-downloads only when a newer
      release has been published.
    """
    if not _db_needs_update():
        return

    _download_db()
    st.rerun()


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

@st.cache_data(ttl=3600)
def top_players_current_year(n: int = 100, min_matches: int = 4) -> pd.DataFrame:
    """Return the top players by win percentage for the current calendar year."""
    year = date.today().year
    start_date = f"{year}-01-01"
    end_date = f"{year + 1}-01-01"

    sql = (
        "SELECT m.slug, p.name, m.wins, m.losses, m.matches, "
        "ROUND(100.0 * m.wins / m.matches, 1) AS win_pct "
        "FROM ("
        "  SELECT slug, SUM(win) wins, SUM(loss) losses, COUNT(*) matches "
        "  FROM ("
        "    SELECT home_slug AS slug, "
        "           CASE WHEN winner='home' THEN 1 ELSE 0 END AS win, "
        "           CASE WHEN winner='home' THEN 0 ELSE 1 END AS loss "
        "    FROM matches "
        "    WHERE status_description=? AND date >= ? AND date < ? "
        "    UNION ALL "
        "    SELECT away_slug AS slug, "
        "           CASE WHEN winner='away' THEN 1 ELSE 0 END AS win, "
        "           CASE WHEN winner='away' THEN 0 ELSE 1 END AS loss "
        "    FROM matches "
        "    WHERE status_description=? AND date >= ? AND date < ? "
        "  ) "
        "  GROUP BY slug "
        "  HAVING COUNT(*) >= ? "
        ") m "
        "JOIN (SELECT slug, MIN(name) AS name FROM players GROUP BY slug) p ON p.slug = m.slug "
        "ORDER BY win_pct DESC, wins DESC, matches DESC "
        "LIMIT ?"
    )

    df = pd.read_sql(
        sql,
        get_conn(),
        params=[ENDED, start_date, end_date, ENDED, start_date, end_date, min_matches, n],
    )
    df["full_name"] = df["slug"].apply(slug_to_full_name)
    df = df.sort_values(
        by=["win_pct", "wins", "matches", "full_name"],
        ascending=[False, False, False, True],
        ignore_index=True,
    )
    return df[["full_name", "name", "wins", "losses", "matches", "win_pct", "slug"]]

@st.cache_data(ttl=3600)
def current_year_latest_date() -> str | None:
    year = date.today().year
    start_date = f"{year}-01-01"
    end_date = f"{year + 1}-01-01"
    df = pd.read_sql(
        "SELECT MAX(date) AS latest_date FROM matches "
        "WHERE status_description=? AND date >= ? AND date < ?",
        get_conn(),
        params=[ENDED, start_date, end_date],
    )
    latest = df.iloc[0, 0] if not df.empty else None
    return latest if latest else None

# ── Player helpers ────────────────────────────────────────────────────────────


# ── Upcoming bets helpers ────────────────────────────────────────────────────

ENRICHED_PATH = Path(__file__).parent / "processed" / "upcoming_enriched.json"

_CONF_ORDER = {"High": 0, "Medium": 1, "Low": 2}


@st.cache_data(ttl=300)
def top_upcoming_bets(n: int = 15) -> pd.DataFrame:
    """Return up to *n* upcoming fixtures sorted by nearest date/time then
    confidence (High > Medium > Low) then win probability descending.

    Columns returned: Date, Time (ET), Home, Away, Favourite, Win %, Confidence, Tournament
    """
    import json
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")

    if not ENRICHED_PATH.exists():
        return pd.DataFrame()
    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return pd.DataFrame()

    fixtures = data.get("fixtures", [])
    if not fixtures:
        return pd.DataFrame()

    df = pd.DataFrame(fixtures)

    # Convert UTC times to ET; keep only fixtures that haven't started yet
    now_et = datetime.now(ET)

    def to_et(row):
        raw_time = row.get("Time", "")
        raw_date = row.get("_date", "")
        if not raw_time or not raw_date:
            return raw_date, raw_time, None
        try:
            dt_utc = datetime.strptime(
                f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
            dt_et = dt_utc.astimezone(ET)
            return dt_et.strftime("%Y-%m-%d"), dt_et.strftime("%H:%M"), dt_et
        except Exception:
            return raw_date, raw_time, None

    et_cols = df.apply(to_et, axis=1, result_type="expand")
    df["_date"] = et_cols[0]
    df["Time"] = et_cols[1]
    df["_dt_et"] = et_cols[2]

    # Filter: only fixtures whose start time (ET) is still in the future
    df = df[df["_dt_et"].apply(lambda x: x is not None and x > now_et)].copy()

    if df.empty:
        return pd.DataFrame()

    # Prioritise leagues available on major sportsbooks (DraftKings etc.)
    _PRIORITY_LEAGUES = ["TT Elite Series", "Czech Liga Pro"]
    df["_league_rank"] = df["Tournament"].apply(
        lambda t: next((i for i, l in enumerate(_PRIORITY_LEAGUES) if l in str(t)), len(_PRIORITY_LEAGUES))
    )

    # Sort: league tier asc, confidence rank asc (High > Medium > Low), then date/time asc, win % desc
    # Confidence field may contain emoji prefix (e.g. "🟢 High") – extract the word
    df["_conf_rank"] = (
        df["Confidence"]
        .astype(str)
        .str.extract(r"(High|Medium|Low)", expand=False)
        .map(_CONF_ORDER)
        .fillna(99)
        .astype(int)
    )
    df["_win_pct_num"] = pd.to_numeric(
        df["Win %"].astype(str).str.rstrip("%"), errors="coerce"
    ).fillna(0)
    df = df.sort_values(
        ["_league_rank", "_conf_rank", "_date", "Time", "_win_pct_num"],
        ascending=[True, True, True, True, False],
    ).head(n)

    out = df[["_date", "Time", "Home", "Away", "Favourite", "Win %", "Confidence", "Tournament"]].copy()
    out = out.rename(columns={"_date": "Date", "Favourite": "Favorite"})
    return out.reset_index(drop=True)

def slug_to_full_name(slug: str) -> str:
    """Derive a display name from a slug by title-casing each hyphen-separated part.

    Examples:
        'chen-weixing'   -> 'Chen Weixing'
        'gardos-robert'  -> 'Gardos Robert'
        'ali-saleh-ahmed'-> 'Ali Saleh Ahmed'
    """
    return " ".join(part.capitalize() for part in slug.split("-"))


@st.cache_data(ttl=3600)
def all_player_names() -> pd.DataFrame:
    """Returns id, name, slug, full_name sorted by full_name."""
    df = pd.read_sql("SELECT id, name, slug FROM players ORDER BY slug", get_conn())
    df["full_name"] = df["slug"].apply(slug_to_full_name)
    return df.sort_values("full_name").reset_index(drop=True)


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
