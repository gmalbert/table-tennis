"""
Table Tennis Historical Data Scraper
=====================================
Sources:
  1. SofaScore  — unofficial JSON API (reverse-engineered from the web app)
  2. Flashscore — binary feed / HTML scraping via Playwright

Usage:
    pip install requests playwright tqdm
    playwright install chromium

    # SofaScore: fetch events for a date range
    python tt_scraper.py sofa --start 2024-01-01 --end 2024-12-31

    # Flashscore: fetch results for a date range
    python tt_scraper.py flash --start 2024-01-01 --end 2024-12-31

    # Both at once
    python tt_scraper.py all --start 2024-01-01 --end 2024-12-31

Output: JSON files written to ./data/sofascore/ and ./data/flashscore/

IMPORTANT NOTES:
  - These are unofficial / reverse-engineered endpoints.  Use responsibly:
      * Keep delays between requests (defaults are conservative).
      * Do NOT hammer the servers – you will get IP-banned.
      * For large historical pulls, run overnight in small date chunks.
  - SofaScore's ToS prohibits commercial use of their data.
  - Flashscore has no public API; scraping may violate their ToS.
  - This script is for personal research / educational use only.
"""

import argparse
import json
import os
import requests
import sys
import time
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from tqdm import tqdm

# ─────────────────────────────────────────────
#  SHARED UTILITIES
# ─────────────────────────────────────────────

def date_range(start: date, end: date):
    """Yield every date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved → {path}")


def random_delay(min_s=1.5, max_s=4.0):
    """Polite random sleep to avoid rate-limiting."""
    time.sleep(random.uniform(min_s, max_s))


# ─────────────────────────────────────────────
#  SOFASCORE SCRAPER
#  Reverse-engineered from the SofaScore web app.
#  Base URL: https://www.sofascore.com/api/v1
#
#  Key endpoints used:
#   /sport/table-tennis/scheduled-events/{YYYY-MM-DD}
#       → list of all TT events on a given day
#   /event/{event_id}/statistics
#       → set scores and match stats per event
#   /event/{event_id}/h2h/events
#       → head-to-head history between the two players
#   /team/{team_id}/events/last/{page}
#       → recent events for a player (TT uses "team" for players)
# ─────────────────────────────────────────────

SOFA_BASE = "https://www.sofascore.com/api/v1"
SOFA_SPORT = "table-tennis"

# ── SofaScore sits behind Cloudflare and validates the full TLS + browser
#    fingerprint, so plain requests / header-copying both fail with 403.
#    The only reliable fix: make every API call *from inside* a real Playwright
#    browser using page.evaluate() / fetch(), which runs in the same JS context
#    that Cloudflare already trusts.  We keep one persistent browser open for
#    the entire run so startup cost is paid only once.


class SofaScoreScraper:
    """
    Pulls table tennis data from SofaScore's internal JSON API.

    Strategy: keep one headless Chromium browser alive for the entire run and
    make every API call via page.evaluate(fetch(...)) — this runs inside the
    browser's JS context, so Cloudflare sees a legitimate browser request with
    the correct TLS fingerprint, cookies, and headers.  No header-copying or
    session-harvesting tricks needed.

    Data collected per match:
      - Tournament / round / stage info
      - Home & away player (team) names + IDs
      - Start time (UTC unix timestamp)
      - Match status & winner
      - Set-by-set scores (via /statistics endpoint)
      - Head-to-head history (optional, --h2h flag)

    Output structure:
      data/sofascore/
        YYYY-MM-DD/
          events.json          ← all event summaries for the day
          {event_id}/
            statistics.json    ← per-set scores
            h2h.json           ← optional H2H history
    """

    def __init__(self, output_dir: Path, fetch_stats=True, fetch_h2h=False):
        self.out = output_dir / "sofascore"
        self.fetch_stats = fetch_stats
        self.fetch_h2h = fetch_h2h
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ── browser lifecycle ──────────────────────────────────────────────────

    def _start_browser(self):
        from playwright.sync_api import sync_playwright
        print("  🌐 Launching browser for SofaScore …")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Block images / fonts / media — we only need JSON responses
        self._context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf,mp4,mp3}",
            lambda r: r.abort(),
        )
        self._page = self._context.new_page()

        # Load the main TT page once so Cloudflare sets its cookies
        print("  ⏳ Loading SofaScore landing page (Cloudflare warm-up) …")
        self._page.goto(
            "https://www.sofascore.com/table-tennis",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        time.sleep(4)

        # Dismiss cookie banner if present
        for sel in [
            "#onetrust-accept-btn-handler",
            "button:has-text('Accept all')",
            "button:has-text('I Accept')",
            "button:has-text('Accept')",
        ]:
            try:
                btn = self._page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    break
            except Exception:
                pass

        print("  ✓ Browser ready.\n")

    def _stop_browser(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ── core fetch — runs fetch() inside the live browser page ────────────

    def _fetch(self, url: str, retries=3) -> dict | None:
        """
        Execute a fetch() call from inside the Playwright page context.
        Because the request originates from the browser, Cloudflare treats it
        as legitimate and returns 200 instead of 403.
        """
        js = f"""
        async () => {{
            const resp = await fetch("{url}", {{
                method: "GET",
                headers: {{
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.sofascore.com/",
                }},
                credentials: "include"
            }});
            if (!resp.ok) return {{ __status: resp.status }};
            return await resp.json();
        }}
        """
        for attempt in range(retries):
            try:
                result = self._page.evaluate(js)
                if result is None:
                    return None
                status = result.get("__status") if isinstance(result, dict) else None
                if status:
                    if status == 404:
                        return None
                    elif status == 429:
                        wait = 30 * (attempt + 1)
                        print(f"  ⚠ Rate limited ({url}). Waiting {wait}s …")
                        time.sleep(wait)
                    elif status == 403:
                        print(f"  ✗ 403 on attempt {attempt+1} for {url} — waiting …")
                        time.sleep(15 * (attempt + 1))
                    else:
                        print(f"  ✗ HTTP {status} for {url}")
                        time.sleep(5)
                else:
                    return result  # success
            except Exception as e:
                print(f"  ✗ evaluate() error: {e}")
                time.sleep(5 * (attempt + 1))
                # If the page crashed, reload it
                try:
                    self._page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                except Exception:
                    pass
        return None

    # ── data methods ───────────────────────────────────────────────────────

    def fetch_day(self, day: date):
        """Fetch all table tennis events scheduled on `day`."""
        day_str = day.strftime("%Y-%m-%d")
        url = f"{SOFA_BASE}/sport/{SOFA_SPORT}/scheduled-events/{day_str}"
        data = self._fetch(url)
        if not data or "events" not in data:
            print(f"  – No events on {day_str}")
            return

        events = data["events"]
        # Filter to finished matches only (status code 100 = finished in SofaScore)
        finished = [e for e in events if e.get("status", {}).get("code") == 100]
        print(f"  → {len(events)} events on {day_str} ({len(finished)} finished)")
        save_json(data, self.out / day_str / "events.json")

        # Skip per-event loop entirely if nothing extra is needed
        if not self.fetch_stats and not self.fetch_h2h:
            return

        for event in finished:
            event_id = event.get("id")
            if not event_id:
                continue
            if self.fetch_stats:
                self._fetch_event_stats(event_id, day_str)
                random_delay(0.8, 1.8)
            if self.fetch_h2h:
                self._fetch_event_h2h(event_id, day_str)
                random_delay(0.8, 1.8)

    def _fetch_event_stats(self, event_id: int, day_str: str):
        url = f"{SOFA_BASE}/event/{event_id}/statistics"
        data = self._fetch(url)
        if data:
            save_json(data, self.out / day_str / str(event_id) / "statistics.json")

    def _fetch_event_h2h(self, event_id: int, day_str: str):
        url = f"{SOFA_BASE}/event/{event_id}/h2h/events"
        data = self._fetch(url)
        if data:
            save_json(data, self.out / day_str / str(event_id) / "h2h.json")

    def fetch_player_history(self, team_id: int, pages=5):
        """Fetch the last N pages of matches for a player (players = 'teams' in SofaScore)."""
        all_events = []
        for page in range(pages):
            url = f"{SOFA_BASE}/team/{team_id}/events/last/{page}"
            data = self._fetch(url)
            if not data or not data.get("events"):
                break
            all_events.extend(data["events"])
            print(f"  → Player {team_id}: page {page}, {len(data['events'])} events")
            random_delay()
        out_path = self.out / "players" / f"{team_id}_history.json"
        save_json({"team_id": team_id, "events": all_events}, out_path)
        return all_events

    def fetch_tournament_seasons(self, tournament_id: int):
        url = f"{SOFA_BASE}/unique-tournament/{tournament_id}/seasons"
        data = self._fetch(url)
        if data:
            save_json(data, self.out / "tournaments" / f"{tournament_id}_seasons.json")
        return data

    def fetch_tournament_standings(self, tournament_id: int, season_id: int):
        url = (
            f"{SOFA_BASE}/unique-tournament/{tournament_id}"
            f"/season/{season_id}/standings/total"
        )
        data = self._fetch(url)
        if data:
            save_json(
                data,
                self.out / "tournaments" / f"{tournament_id}_{season_id}_standings.json",
            )
        return data

    def run(self, start: date, end: date):
        print(f"\n{'='*55}")
        print(f"  SofaScore: {start} → {end}")
        print(f"{'='*55}")
        self._start_browser()
        try:
            days = list(date_range(start, end))
            for day in tqdm(days, desc="SofaScore days"):
                self.fetch_day(day)
                random_delay(1.0, 2.5)
        finally:
            self._stop_browser()
        print("  ✓ SofaScore done.\n")


# ─────────────────────────────────────────────
#  FLASHSCORE SCRAPER
#
#  Flashscore exposes a private "ninja" feed API at:
#    https://global.flashscore.ninja/2/x/feed/f_25_{offset}_-4_en_1
#
#  where {offset} is the day offset from today (0 = today, -1 = yesterday, …).
#  The API uses a custom delimited text format (÷ / ¬ / ~).
#
#  IMPORTANT LIMITATION: The ninja API only serves a rolling window of
#  approximately the last 7 days. Older dates return a single "0" byte.
#  For historical data older than 1 week, Flashscore data is not available
#  through this method — use SofaScore (which has full history) instead.
#
#  Output:
#    data/flashscore/
#      YYYY-MM-DD/
#        matches.json   ← list of matches + set scores for the day
# ─────────────────────────────────────────────

FLASH_BASE = "https://www.flashscore.com"
FLASH_NINJA = "https://global.flashscore.ninja/2/x/feed"
FLASH_SPORT_ID = 25  # Table Tennis
FLASH_NINJA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.flashscore.com/",
    "x-fsign": "SW9D1eZo",
}
# Maximum days back the API reliably serves data for
FLASH_MAX_DAYS_BACK = 7


def _parse_ninja_feed(text: str, date_str: str) -> list[dict]:
    """
    Parse the Flashscore ninja feed format into a list of match dicts.

    Format overview:
      Records separated by ~
      Fields within a record separated by ¬
      Key÷value within each field

    Tournament header records start with ZA÷{name}
    Match records start with AA÷{match_id}

    Key field codes used:
      AA = match ID          AD = start timestamp (unix)
      AE = home player       AF = away player
      AG = home sets won     AH = away sets won
      BA/BC/BE/BG/BI = home set scores 1-5
      BB/BD/BF/BH/BJ = away set scores 1-5
      BK/BM = home set scores 6-7
      BL/BN = away set scores 6-7
      CA = home ranking      CB = away ranking
      JA = home slug         JB = away slug
      WU = home slug (url)   WV = away slug (url)
    """
    matches = []
    if not text or text.strip() in ("", "0"):
        return matches

    records = text.split("~")
    current_tournament = "Unknown"

    for record in records:
        if not record.strip():
            continue
        fields = {
            k: v
            for part in record.split("¬")
            if "÷" in part
            for k, v in [part.split("÷", 1)]
        }
        if not fields:
            continue

        # Tournament header
        if "ZA" in fields:
            raw = fields["ZA"]
            # Strip trailing encoding artifacts like '031World)' etc.
            current_tournament = raw.split("\x00")[0].strip()

        # Match record
        if "AA" not in fields:
            continue

        ts = fields.get("AD", "")
        start_time = ""
        if ts:
            try:
                from datetime import datetime, timezone as _tz
                start_time = datetime.fromtimestamp(int(ts), tz=_tz.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                start_time = ts

        home = fields.get("AE", fields.get("CX", ""))
        away = fields.get("AF", "")
        home_sets = fields.get("AG", "")
        away_sets = fields.get("AH", "")

        # Set scores: BA/BB=set1, BC/BD=set2, BE/BF=set3, BG/BH=set4, BI/BJ=set5, BK/BL=set6, BM/BN=set7
        set_pairs = [("BA", "BB"), ("BC", "BD"), ("BE", "BF"), ("BG", "BH"), ("BI", "BJ"), ("BK", "BL"), ("BM", "BN")]
        sets = [
            {"home": fields[hk], "away": fields[ak]}
            for hk, ak in set_pairs
            if hk in fields or ak in fields
        ]

        match = {
            "match_id": fields["AA"],
            "tournament": current_tournament,
            "home_player": home,
            "away_player": away,
            "score_home": home_sets,
            "score_away": away_sets,
            "time": start_time,
            "home_ranking": fields.get("CA", ""),
            "away_ranking": fields.get("CB", ""),
            "home_slug": fields.get("WU", fields.get("JA", "")),
            "away_slug": fields.get("WV", fields.get("JB", "")),
            "sets": sets,
        }

        if home and away:
            matches.append(match)

    return matches


class FlashscoreScraper:
    """
    Pulls table tennis results from the Flashscore ninja feed API.
    No browser required — pure HTTP requests.

    Limitation: only the last ~7 days are available via this API.
    Dates older than FLASH_MAX_DAYS_BACK will be skipped with a warning.
    """

    def __init__(self, output_dir: Path, detail_pages=True):
        self.out = output_dir / "flashscore"
        # detail_pages flag is kept for API compatibility but is a no-op;
        # the ninja feed already includes set-level scores.
        self.detail_pages = detail_pages

    def _check_playwright(self):
        """No-op — Playwright is no longer required for Flashscore."""
        pass

    def fetch_day(self, day: date) -> int:
        """Fetch all table tennis results for a single day. Returns match count."""
        day_str = day.strftime("%Y-%m-%d")
        today = date.today()
        days_back = (today - day).days

        if days_back > FLASH_MAX_DAYS_BACK:
            return -1  # signal: out of range

        offset = days_back * -1
        url = f"{FLASH_NINJA}/f_{FLASH_SPORT_ID}_{offset}_-4_en_1"

        try:
            resp = requests.get(url, headers=FLASH_NINJA_HEADERS, timeout=15)
            resp.raise_for_status()
            matches = _parse_ninja_feed(resp.text, day_str)
        except Exception as e:
            print(f"  ✗ Error fetching Flashscore {day_str}: {e}")
            matches = []

        save_json(
            {"date": day_str, "match_count": len(matches), "matches": matches},
            self.out / day_str / "matches.json",
        )
        return len(matches)

    def run(self, start: date, end: date):
        today = date.today()
        max_start = today - timedelta(days=FLASH_MAX_DAYS_BACK)

        print(f"\n{'='*55}")
        print(f"  Flashscore: {start} → {end}")
        print(f"{'='*55}")

        days = list(date_range(start, end))

        skipped = [d for d in days if d < max_start]
        in_range = [d for d in days if d >= max_start]

        if skipped:
            print(
                f"  ⚠ Flashscore ninja API only covers the last {FLASH_MAX_DAYS_BACK} days.\n"
                f"    {len(skipped)} day(s) before {max_start} will be skipped.\n"
                f"    Use SofaScore (--source sofa) for historical data.\n"
            )

        if not in_range:
            print("  – No days in range. Nothing to fetch.")
            return

        total = 0
        for day in tqdm(in_range, desc="Flashscore days", unit="day"):
            count = self.fetch_day(day)
            if count >= 0:
                print(f"  → {count} matches on {day}")
                total += count
            random_delay(0.5, 1.5)

        print(f"  ✓ Flashscore done — {total} matches fetched.\n")



FLASH_BASE = "https://www.flashscore.com"
FLASH_TT_URL = f"{FLASH_BASE}/table-tennis/"




# ─────────────────────────────────────────────
#  KNOWN SOFASCORE TABLE TENNIS TOURNAMENT IDs


# ─────────────────────────────────────────────
#  KNOWN SOFASCORE TABLE TENNIS TOURNAMENT IDs
#  (Found by inspecting URLs on sofascore.com)
#  Update as needed — tournament IDs are stable.
# ─────────────────────────────────────────────

KNOWN_TOURNAMENTS = {
    # WTT events
    "WTT Cup Finals": 63218,
    "WTT Grand Smash Saudi Smash": 63219,
    "WTT Champions": 63220,
    # ITTF World Tour / WTT Contender events are in the 6xxxx range
    # Use fetch_tournament_seasons() to discover season IDs for each.
}


# ─────────────────────────────────────────────
#  CLI ENTRY POINT
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Table Tennis Historical Data Scraper (SofaScore + Flashscore)"
    )
    parser.add_argument(
        "source",
        choices=["sofa", "flash", "all"],
        help="Which source to scrape",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--output",
        default="./data",
        help="Root output directory (default: ./data)",
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="SofaScore: skip per-event statistics fetch",
    )
    parser.add_argument(
        "--h2h",
        action="store_true",
        help="SofaScore: also fetch head-to-head history per match",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Flashscore: skip match detail pages (faster but no set scores)",
    )
    parser.add_argument(
        "--player-ids",
        nargs="*",
        type=int,
        metavar="ID",
        help="SofaScore: also fetch last-match history for these player (team) IDs",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    if args.source in ("sofa", "all"):
        sofa = SofaScoreScraper(
            output_dir=out,
            fetch_stats=not args.no_stats,
            fetch_h2h=args.h2h,
        )
        sofa.run(args.start, args.end)

        if args.player_ids:
            print("Fetching player histories …")
            for pid in args.player_ids:
                sofa.fetch_player_history(pid)
                random_delay(3, 6)

    if args.source in ("flash", "all"):
        flash = FlashscoreScraper(
            output_dir=out,
            detail_pages=not args.no_detail,
        )
        flash.run(args.start, args.end)

    print("\n✅ All done. Data written to:", out.resolve())


if __name__ == "__main__":
    main()
