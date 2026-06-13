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
    python scripts/tt_precompute.py --flash-only

Or from the repo root after scraping:
    python scripts/tt_scraper.py sofa --start DATE --end DATE+3 --no-stats
    python scripts/tt_precompute.py
"""

from __future__ import annotations

import argparse
import json
import math
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
IDENTITY_MAP_PATH = ROOT / "processed" / "player_identity_map.json"
PRECOMP_CACHE_PATH = ROOT / "processed" / "precompute_cache.json"

_FINISHED_CODES = {100, 70}   # SofaScore: 100=Ended, 70=Cancelled


def _norm_name(v: str) -> str:
    return " ".join(str(v or "").strip().lower().split())


def _load_identity_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Return normalized-name -> canonical slug map, persisted for reuse."""
    if IDENTITY_MAP_PATH.exists():
        try:
            payload = json.loads(IDENTITY_MAP_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items()}
        except Exception:
            pass

    dfp = pd.read_sql("SELECT slug, name FROM players WHERE slug IS NOT NULL AND slug <> ''", conn)
    mapping: dict[str, str] = {}
    for _, row in dfp.iterrows():
        slug = str(row.get("slug", "")).strip()
        name = _norm_name(row.get("name", ""))
        if slug and name and name not in mapping:
            mapping[name] = slug

    IDENTITY_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_MAP_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapping


def _resolve_slug(name: str, slug: str, identity_map: dict[str, str]) -> str:
    s = str(slug or "").strip()
    if s:
        return s
    return identity_map.get(_norm_name(name), "")


def _load_precompute_cache() -> dict:
    if not PRECOMP_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(PRECOMP_CACHE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_precompute_cache(payload: dict) -> None:
    PRECOMP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRECOMP_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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


def collect_fixtures(days_ahead: int = 7, flash_only: bool = False) -> list[dict]:
    today = date.today()
    raw: list[dict] = []
    for i in range(days_ahead + 1):
        d = today + timedelta(days=i)
        sofa = [] if flash_only else load_sofascore_upcoming(d)
        flash = load_flashscore_upcoming(d)

        # When both feeds are enabled, keep SofaScore precedence for duplicate pairs.
        if sofa:
            sofa_pairs = {(r["home_slug"], r["away_slug"]) for r in sofa}
            flash = [r for r in flash if (r["home_slug"], r["away_slug"]) not in sofa_pairs]
        raw.extend(sofa)
        raw.extend(flash)

    # Canonical identity mapping so cross-source fixtures can use consistent player keys.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    try:
        identity_map = _load_identity_map(conn)
    finally:
        conn.close()

    for r in raw:
        r["home_slug"] = _resolve_slug(r.get("home_player", ""), r.get("home_slug", ""), identity_map)
        r["away_slug"] = _resolve_slug(r.get("away_player", ""), r.get("away_slug", ""), identity_map)

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

    pair_keys = {
        "|".join(sorted((r.get("home_slug", ""), r.get("away_slug", ""))))
        for r in rows
        if r.get("home_slug") and r.get("away_slug")
    }

    CHUNK = 450
    date_cutoff = (date.today() - timedelta(days=3 * 365)).isoformat()
    db_mtime = int(DB_PATH.stat().st_mtime) if DB_PATH.exists() else 0

    cache = _load_precompute_cache()
    slug_cache = cache.get("slug_stats", {}) if isinstance(cache.get("slug_stats", {}), dict) else {}
    pair_cache = cache.get("pair_stats", {}) if isinstance(cache.get("pair_stats", {}), dict) else {}

    cache_valid = (
        cache.get("cache_date") == date.today().isoformat()
        and int(cache.get("db_mtime", 0)) == db_mtime
    )

    if not cache_valid:
        slug_cache = {}
        pair_cache = {}

    missing_slugs = [s for s in all_slugs if s not in slug_cache]
    missing_pairs = [k for k in pair_keys if k not in pair_cache]

    if missing_slugs or missing_pairs:
        parts: list[pd.DataFrame] = []
        for i in range(0, len(all_slugs), CHUNK):
            chunk = all_slugs[i : i + CHUNK]
            if not chunk:
                continue
            ph = ",".join("?" * len(chunk))
            sql = (
                f"SELECT rowid, home_slug, away_slug, winner, date FROM matches "
                f"WHERE status_description='Ended' AND date >= ? AND home_slug IN ({ph}) "
                f"UNION ALL "
                f"SELECT rowid, home_slug, away_slug, winner, date FROM matches "
                f"WHERE status_description='Ended' AND date >= ? AND away_slug IN ({ph})"
            )
            parts.append(pd.read_sql(sql, conn, params=[date_cutoff] + chunk + [date_cutoff] + chunk))

        if parts:
            all_m = (
                pd.concat(parts, ignore_index=True)
                .drop_duplicates(subset="rowid")
                .sort_values("date", ascending=False)
                .reset_index(drop=True)
            )
        else:
            all_m = pd.DataFrame(columns=["rowid", "home_slug", "away_slug", "winner", "date"])

        for slug in missing_slugs:
            pm = all_m[(all_m["home_slug"] == slug) | (all_m["away_slug"] == slug)]
            if pm.empty:
                slug_cache[slug] = {"overall": 0.5, "recent": 0.5, "matches": 0}
                continue
            won = (
                ((pm["home_slug"] == slug) & (pm["winner"] == "home")) |
                ((pm["away_slug"] == slug) & (pm["winner"] == "away"))
            )
            slug_cache[slug] = {
                "overall": float(won.mean()),
                "recent": float(won.iloc[:20].mean()),
                "matches": int(len(pm)),
            }

        for key in missing_pairs:
            s1, s2 = key.split("|", 1)
            h2h = all_m[
                ((all_m["home_slug"] == s1) & (all_m["away_slug"] == s2)) |
                ((all_m["home_slug"] == s2) & (all_m["away_slug"] == s1))
            ]
            total = int(len(h2h))
            w1 = int(
                ((h2h["home_slug"] == s1) & (h2h["winner"] == "home")).sum() +
                ((h2h["away_slug"] == s1) & (h2h["winner"] == "away")).sum()
            ) if total else 0
            pair_cache[key] = {
                "total": total,
                "wins_s1": w1,
                "rate_s1": (w1 / total) if total else 0.5,
            }

        _save_precompute_cache(
            {
                "cache_date": date.today().isoformat(),
                "db_mtime": db_mtime,
                "slug_stats": slug_cache,
                "pair_stats": pair_cache,
            }
        )

    conn.close()

    def _to_rank(v: str | int | float | None) -> int | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s == "–":
            return None
        try:
            return int(s)
        except Exception:
            return None

    def _rank_prob_home(home_rank: int, away_rank: int) -> float:
        # Lower ranking number means stronger player.
        diff = away_rank - home_rank
        p = 1.0 / (1.0 + math.exp(-diff / 60.0))
        return min(0.85, max(0.15, p))

    enriched = []
    for m in rows:
        slug1 = m.get("home_slug", "")
        slug2 = m.get("away_slug", "")
        name1 = m.get("home_player", "?")
        name2 = m.get("away_player", "?")
        sched = m.get("time", "")

        s1_stats = slug_cache.get(slug1, {"overall": 0.5, "recent": 0.5, "matches": 0})
        s2_stats = slug_cache.get(slug2, {"overall": 0.5, "recent": 0.5, "matches": 0})
        overall1 = float(s1_stats.get("overall", 0.5))
        overall2 = float(s2_stats.get("overall", 0.5))
        recent1 = float(s1_stats.get("recent", 0.5))
        recent2 = float(s2_stats.get("recent", 0.5))

        h2h_total = 0
        h2h_w1 = 0
        h2h_rate1 = 0.5
        if slug1 and slug2:
            key = "|".join(sorted((slug1, slug2)))
            ps = pair_cache.get(key)
            if ps:
                h2h_total = int(ps.get("total", 0))
                if key.split("|", 1)[0] == slug1:
                    h2h_w1 = int(ps.get("wins_s1", 0))
                    h2h_rate1 = float(ps.get("rate_s1", 0.5))
                else:
                    wins_for_first = int(ps.get("wins_s1", 0))
                    h2h_w1 = h2h_total - wins_for_first
                    h2h_rate1 = (h2h_w1 / h2h_total) if h2h_total else 0.5

        if h2h_total >= 5:   w_h2h, w_r, w_o = 0.50, 0.25, 0.25
        elif h2h_total >= 1: w_h2h, w_r, w_o = 0.25, 0.375, 0.375
        else:                w_h2h, w_r, w_o = 0.00, 0.50, 0.50

        prob1 = w_h2h * h2h_rate1 + w_r * recent1 + w_o * overall1

        # When both players are unknown to slug history/H2H, use ranking signal
        # to avoid flat 50/50 predictions.
        if h2h_total == 0 and overall1 == 0.5 and overall2 == 0.5 and recent1 == 0.5 and recent2 == 0.5:
            hr = _to_rank(m.get("home_ranking"))
            ar = _to_rank(m.get("away_ranking"))
            if hr and ar:
                prob1 = _rank_prob_home(hr, ar)

        prob2 = 1 - prob1
        fav      = name1 if prob1 >= prob2 else name2
        fav_prob = max(prob1, prob2)
        margin   = abs(prob1 - prob2)
        if margin >= 0.15:   conf_label, conf_icon = "High",   "🟢"
        elif margin >= 0.07: conf_label, conf_icon = "Medium", "🟡"
        else:                conf_label, conf_icon = "Low",    "🔴"

        h2h_l = h2h_total - h2h_w1
        player_cov = min(1.0, (int(s1_stats.get("matches", 0)) + int(s2_stats.get("matches", 0))) / 200.0)
        h2h_cov = min(1.0, h2h_total / 10.0)
        coverage_score = round(100.0 * (0.7 * player_cov + 0.3 * h2h_cov), 1)
        if coverage_score >= 75:
            coverage_tier = "High"
        elif coverage_score >= 40:
            coverage_tier = "Medium"
        else:
            coverage_tier = "Low"

        explain_parts = [
            f"h2h={h2h_total}",
            f"recent_w={w_r:.3f}",
            f"overall_w={w_o:.3f}",
            f"h2h_w={w_h2h:.3f}",
            f"cover={coverage_score:.1f}",
        ]
        if h2h_total == 0 and overall1 == 0.5 and overall2 == 0.5 and recent1 == 0.5 and recent2 == 0.5:
            explain_parts.append("rank_fallback=1")

        enriched.append({
            "_date":          m["_date"],
            "_source":        m.get("_source", ""),
            "_conf_label":    conf_label,
            "_coverage_tier": coverage_tier,
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
            "Coverage":       f"{coverage_score:.1f}",
            "Coverage Tier":  coverage_tier,
            "Sample Size":    int(s1_stats.get("matches", 0)) + int(s2_stats.get("matches", 0)),
            "Model Explain":  " | ".join(explain_parts),
            "H2H (home W-L)": f"{h2h_w1}-{h2h_l} ({h2h_total})" if h2h_total else "–",
            "Home Recent":    f"{recent1 * 100:.0f}%",
            "Away Recent":    f"{recent2 * 100:.0f}%",
            "Home Overall":   f"{overall1 * 100:.0f}%",
            "Away Overall":   f"{overall2 * 100:.0f}%",
        })

    return enriched


# ── Main ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Precompute upcoming enriched fixtures")
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Number of days ahead (inclusive) to collect fixtures for.",
    )
    parser.add_argument(
        "--flash-only",
        action="store_true",
        help="Use Flashscore fixtures only (skip SofaScore).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        print("Run scripts/tt_build_db.py first.", file=sys.stderr)
        sys.exit(1)

    print("Collecting upcoming fixtures …")
    fixtures = collect_fixtures(days_ahead=max(0, int(args.days_ahead)), flash_only=args.flash_only)
    source_mode = "flash-only" if args.flash_only else "sofascore+flashscore"
    print(f"  Source mode: {source_mode}")
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
