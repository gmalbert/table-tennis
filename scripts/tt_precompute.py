"""
Nightly pre-computation script for upcoming match predictions.

Reads SofaScore (and optionally Flashscore) fixture files for today + the
next 7 days, enriches every fixture with win-probability and H2H stats from
the historical SQLite DB, and writes the result to:

    processed/upcoming_enriched.json

The Streamlit page (pages/6_Upcoming_Matches.py) reads this file directly so
it loads instantly with no on-demand computation.

Run manually:
    python scripts/tt_precompute.py

Or from the repo root after scraping:
    python scripts/tt_scraper.py sofa --start DATE --end DATE+3 --no-stats
    python scripts/tt_precompute.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).parent.parent
SOFA_DIR  = ROOT / "data" / "sofascore"
FLASH_DIR = ROOT / "data" / "flashscore"
DB_PATH   = ROOT / "processed" / "tt.db"
OUT_PATH  = ROOT / "processed" / "upcoming_enriched.json"

_FINISHED_CODES = {100, 70}   # SofaScore: 100=Ended, 70=Cancelled

# ── Loaders ────────────────────────────────────────────────────────────────────

def _sofa_tournament_name(event: dict) -> str:
    t = event.get("tournament", {}).get("name", "")
    s = event.get("season", {}).get("name", "")
    return f"{t} – {s}" if s else t


def load_sofascore_upcoming(day: date) -> list[dict]:
    f = SOFA_DIR / day.isoformat() / "events.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for e in data.get("events", []):
        if e.get("status", {}).get("code", -1) in _FINISHED_CODES:
            continue
        ht = e.get("homeTeam", {})
        at = e.get("awayTeam", {})
        ts = e.get("startTimestamp", 0)
        scheduled = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if ts else ""
        )
        rows.append({
            "match_id":     str(e.get("id", "")),
            "tournament":   _sofa_tournament_name(e),
            "home_player":  ht.get("name", ""),
            "away_player":  at.get("name", ""),
            "home_slug":    ht.get("slug", ""),
            "away_slug":    at.get("slug", ""),
            "time":         scheduled,
            "home_ranking": "",
            "away_ranking": "",
            "_date":        day.isoformat(),
            "_source":      "sofascore",
        })
    return rows


def load_flashscore_upcoming(day: date) -> list[dict]:
    f = FLASH_DIR / day.isoformat() / "matches.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for m in data.get("matches", []):
        if not m.get("score_home") and not m.get("score_away"):
            rows.append({**m, "_date": day.isoformat(), "_source": "flashscore"})
    return rows


def collect_fixtures(days_ahead: int = 7) -> list[dict]:
    today = date.today()
    raw: list[dict] = []
    for i in range(days_ahead + 1):
        d = today + timedelta(days=i)
        sofa  = load_sofascore_upcoming(d)
        flash = load_flashscore_upcoming(d)
        if sofa:
            sofa_pairs = {(r["home_slug"], r["away_slug"]) for r in sofa}
            flash = [r for r in flash if (r["home_slug"], r["away_slug"]) not in sofa_pairs]
        raw.extend(sofa)
        raw.extend(flash)
    return raw


# ── Enrichment ─────────────────────────────────────────────────────────────────

def enrich(rows: list[dict]) -> list[dict]:
    """Add win-probability, H2H, and form stats to every fixture row."""
    if not rows:
        return []

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")

    all_slugs = sorted({
        slug
        for r in rows
        for slug in (r.get("home_slug", ""), r.get("away_slug", ""))
        if slug
    })

    CHUNK = 450
    # 3-year cutoff keeps stats relevant; date index makes this fast
    date_cutoff = (date.today() - timedelta(days=3 * 365)).isoformat()
    parts: list[pd.DataFrame] = []
    for i in range(0, len(all_slugs), CHUNK):
        chunk = all_slugs[i : i + CHUNK]
        ph = ",".join("?" * len(chunk))
        # UNION ALL instead of OR so SQLite can use idx_m_home_slug + idx_m_away_slug
        sql = (
            f"SELECT rowid, home_slug, away_slug, winner, date FROM matches "
            f"WHERE status_description='Ended' AND date >= ? AND home_slug IN ({ph}) "
            f"UNION ALL "
            f"SELECT rowid, home_slug, away_slug, winner, date FROM matches "
            f"WHERE status_description='Ended' AND date >= ? AND away_slug IN ({ph})"
        )
        parts.append(pd.read_sql(sql, conn, params=[date_cutoff] + chunk + [date_cutoff] + chunk))
    conn.close()

    if parts:
        all_m = (
            pd.concat(parts, ignore_index=True)
            .drop_duplicates(subset="rowid")
            .sort_values("date", ascending=False)
            .reset_index(drop=True)
        )
    else:
        all_m = pd.DataFrame(columns=["rowid", "home_slug", "away_slug", "winner", "date"])

    slug_overall: dict[str, float] = {}
    slug_recent:  dict[str, float] = {}
    for slug in all_slugs:
        pm = all_m[(all_m["home_slug"] == slug) | (all_m["away_slug"] == slug)]
        if pm.empty:
            slug_overall[slug] = slug_recent[slug] = 0.5
            continue
        won = (
            ((pm["home_slug"] == slug) & (pm["winner"] == "home")) |
            ((pm["away_slug"] == slug) & (pm["winner"] == "away"))
        )
        slug_overall[slug] = float(won.mean())
        slug_recent[slug]  = float(won.iloc[:20].mean())

    enriched = []
    for m in rows:
        slug1 = m.get("home_slug", "")
        slug2 = m.get("away_slug", "")
        name1 = m.get("home_player", "?")
        name2 = m.get("away_player", "?")
        sched = m.get("time", "")

        overall1 = slug_overall.get(slug1, 0.5)
        overall2 = slug_overall.get(slug2, 0.5)
        recent1  = slug_recent.get(slug1,  0.5)
        recent2  = slug_recent.get(slug2,  0.5)

        if slug1 and slug2 and not all_m.empty:
            h2h = all_m[
                ((all_m["home_slug"] == slug1) & (all_m["away_slug"] == slug2)) |
                ((all_m["home_slug"] == slug2) & (all_m["away_slug"] == slug1))
            ]
            h2h_total = len(h2h)
            h2h_w1 = int(
                ((h2h["home_slug"] == slug1) & (h2h["winner"] == "home")).sum() +
                ((h2h["away_slug"] == slug1) & (h2h["winner"] == "away")).sum()
            ) if h2h_total else 0
            h2h_rate1 = h2h_w1 / h2h_total if h2h_total else 0.5
        else:
            h2h_total = h2h_w1 = 0
            h2h_rate1 = 0.5

        if h2h_total >= 5:   w_h2h, w_r, w_o = 0.50, 0.25, 0.25
        elif h2h_total >= 1: w_h2h, w_r, w_o = 0.25, 0.375, 0.375
        else:                w_h2h, w_r, w_o = 0.00, 0.50, 0.50

        prob1    = w_h2h * h2h_rate1 + w_r * recent1 + w_o * overall1
        prob2    = 1 - prob1
        fav      = name1 if prob1 >= prob2 else name2
        fav_prob = max(prob1, prob2)
        margin   = abs(prob1 - prob2)
        if margin >= 0.15:   conf_label, conf_icon = "High",   "🟢"
        elif margin >= 0.07: conf_label, conf_icon = "Medium", "🟡"
        else:                conf_label, conf_icon = "Low",    "🔴"

        h2h_l = h2h_total - h2h_w1
        enriched.append({
            "_date":          m["_date"],
            "_source":        m.get("_source", ""),
            "_conf_label":    conf_label,
            "Date":           m["_date"],
            "Time":           sched[11:16] if len(sched) >= 16 else "",
            "Tournament":     m.get("tournament", ""),
            "Home":           name1,
            "Away":           name2,
            "Home Rank":      m.get("home_ranking", "") or "–",
            "Away Rank":      m.get("away_ranking", "") or "–",
            "Favourite":      fav,
            "Win %":          f"{fav_prob * 100:.0f}%",
            "Confidence":     f"{conf_icon} {conf_label}",
            "H2H (home W-L)": f"{h2h_w1}-{h2h_l} ({h2h_total})" if h2h_total else "–",
            "Home Recent":    f"{recent1 * 100:.0f}%",
            "Away Recent":    f"{recent2 * 100:.0f}%",
            "Home Overall":   f"{overall1 * 100:.0f}%",
            "Away Overall":   f"{overall2 * 100:.0f}%",
        })

    return enriched


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        print("Run scripts/tt_build_db.py first.", file=sys.stderr)
        sys.exit(1)

    print("Collecting upcoming fixtures …")
    fixtures = collect_fixtures(days_ahead=7)
    print(f"  Found {len(fixtures)} upcoming fixtures across {len({r['_date'] for r in fixtures})} days")

    if not fixtures:
        print("No fixtures found — writing empty output.")
        out = {"generated_at": datetime.now(tz=timezone.utc).isoformat(), "fixtures": []}
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    print("Enriching with historical stats …")
    enriched = enrich(fixtures)
    print(f"  Enriched {len(enriched)} fixtures")

    out = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "fixtures": enriched,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ Written → {OUT_PATH}")


if __name__ == "__main__":
    main()
