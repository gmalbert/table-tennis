"""Fetch and normalize ITTF rankings into a versioned JSON snapshot.

The official rankings page changes frequently, so the parser accepts either a
JSON feed or table-shaped HTML.  Set ITTF_RANKINGS_URL when the federation
publishes a more specific endpoint; no credential is required.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.frontier_model import stable_player_id
from models.audit_store import append_rankings

DEFAULT_URL = "https://www.ittf.com/rankings/"
OUT_PATH = ROOT / "processed" / "ittf_rankings.json"


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _from_json(payload: object, category: str) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        raw_rows = payload.get("rankings") or payload.get("rows") or payload.get("data") or []
    else:
        raw_rows = payload
    rows: list[dict[str, object]] = []
    if not isinstance(raw_rows, list):
        return rows
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("player") or item.get("name") or "").strip()
        rank = item.get("rank") or item.get("position")
        if not name or not str(rank).isdigit():
            continue
        rows.append(
            {
                "rank": int(rank),
                "player": name,
                "country": str(item.get("country") or item.get("association") or ""),
                "points": float(item.get("points") or 0),
                "category": category,
                "stable_id": stable_player_id(name, "ittf", str(item.get("id") or "")),
            }
        )
    return rows


def _from_html(text: str, category: str) -> list[dict[str, object]]:
    parser = TableParser()
    parser.feed(text)
    rows: list[dict[str, object]] = []
    for cells in parser.rows:
        if len(cells) < 2:
            continue
        rank_match = re.search(r"\d+", cells[0])
        if not rank_match:
            continue
        rank = int(rank_match.group())
        if rank > 1000:
            continue
        name = cells[1].strip()
        if not name or name.casefold() in {"player", "name"}:
            continue
        country = cells[2] if len(cells) > 2 else ""
        points_text = re.sub(r"[^0-9.]", "", cells[3] if len(cells) > 3 else "0")
        rows.append(
            {
                "rank": rank,
                "player": name,
                "country": country,
                "points": float(points_text or 0),
                "category": category,
                "stable_id": stable_player_id(name, "ittf"),
            }
        )
    return rows


def fetch_rankings(category: str, url: str, timeout: int = 30) -> list[dict[str, object]]:
    response = requests.get(url, headers={"User-Agent": "PongOdds/1.0 (+rankings research)"}, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return _from_json(response.json(), category)
    return _from_html(response.text, category)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--url", default=os.getenv("ITTF_RANKINGS_URL", "").strip() or DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    categories = args.category or ["mens_singles", "womens_singles"]
    rankings: list[dict[str, object]] = []
    errors: list[str] = []
    for category in categories:
        try:
            rankings.extend(fetch_rankings(category, args.url))
        except Exception as exc:
            errors.append(f"{category}: {exc}")
    observed_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "observed_at": observed_at,
        "source": args.url,
        "rankings": rankings,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if rankings:
        print(f"Archived {append_rankings(rankings, observed_at)} ranking rows")
    print(f"Wrote {len(rankings)} ranking rows to {args.output}")
    if not rankings:
        raise SystemExit("No rankings parsed; snapshot retained with diagnostic errors")


if __name__ == "__main__":
    main()
