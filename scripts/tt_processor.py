"""
Table Tennis Data Post-Processor
==================================
Reads the raw JSON files produced by tt_scraper.py and outputs:
  - matches.csv        : one row per match (both sources combined)
  - sets.csv           : one row per set played
  - players.csv        : unique player roster with IDs

Usage:
    python tt_processor.py --data ./data --output ./processed
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm


# ─── SofaScore flattening ─────────────────────────────────────────────────────

def sofa_unix_to_str(ts) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def flatten_sofa_event(event: dict, stats: dict | None = None) -> dict:
    """Flatten one SofaScore event dict into a row-friendly dict."""
    home = event.get("homeTeam", {})
    away = event.get("awayTeam", {})
    score = event.get("homeScore", {})
    away_score = event.get("awayScore", {})
    tournament = event.get("tournament", {})
    round_info = event.get("roundInfo", {})
    status = event.get("status", {})

    row = {
        "source": "sofascore",
        "event_id": event.get("id"),
        "start_time_utc": sofa_unix_to_str(event.get("startTimestamp")),
        "tournament_name": tournament.get("name", ""),
        "tournament_id": tournament.get("uniqueTournament", {}).get("id", ""),
        "round": round_info.get("round", ""),
        "round_name": round_info.get("name", ""),
        "status_code": status.get("code", ""),
        "status_description": status.get("description", ""),
        "home_id": home.get("id"),
        "home_name": home.get("name", ""),
        "home_slug": home.get("slug", ""),
        "away_id": away.get("id"),
        "away_name": away.get("name", ""),
        "away_slug": away.get("slug", ""),
        # Main score = sets won
        "home_sets_won": score.get("current", ""),
        "away_sets_won": away_score.get("current", ""),
        # Period scores = individual set scores
        "home_set1": score.get("period1", ""),
        "away_set1": away_score.get("period1", ""),
        "home_set2": score.get("period2", ""),
        "away_set2": away_score.get("period2", ""),
        "home_set3": score.get("period3", ""),
        "away_set3": away_score.get("period3", ""),
        "home_set4": score.get("period4", ""),
        "away_set4": away_score.get("period4", ""),
        "home_set5": score.get("period5", ""),
        "away_set5": away_score.get("period5", ""),
        "home_set6": score.get("period6", ""),
        "away_set6": away_score.get("period6", ""),
        "home_set7": score.get("period7", ""),
        "away_set7": away_score.get("period7", ""),
        "winner": "",
    }

    # Determine winner
    h = row["home_sets_won"]
    a = row["away_sets_won"]
    if h != "" and a != "":
        try:
            row["winner"] = "home" if int(h) > int(a) else "away"
        except ValueError:
            pass

    return row


def flatten_sofa_sets(event_id, event: dict) -> list[dict]:
    """Expand per-set scores into individual rows."""
    home = event.get("homeTeam", {}).get("name", "")
    away = event.get("awayTeam", {}).get("name", "")
    home_score = event.get("homeScore", {})
    away_score = event.get("awayScore", {})
    rows = []
    for i in range(1, 8):
        key = f"period{i}"
        h = home_score.get(key)
        a = away_score.get(key)
        if h is None and a is None:
            break
        rows.append({
            "source": "sofascore",
            "event_id": event_id,
            "home_name": home,
            "away_name": away,
            "set_number": i,
            "home_points": h,
            "away_points": a,
            "set_winner": "home" if (h or 0) > (a or 0) else "away",
        })
    return rows


def process_sofascore(data_dir: Path, out_dir: Path, checkpoint: set, checkpoint_file: Path):
    all_players = {}
    total_matches = 0
    total_sets = 0

    sofa_dir = data_dir / "sofascore"
    if not sofa_dir.exists():
        print("  – No SofaScore data found.")
        return all_players, total_matches, total_sets

    day_dirs = sorted(sofa_dir.iterdir())
    skipped = sum(1 for d in day_dirs if f"sofa:{d.name}" in checkpoint)
    if skipped:
        print(f"  Resuming — skipping {skipped} already-processed days")

    match_path = out_dir / "matches.csv"
    set_path = out_dir / "sets.csv"

    for day_dir in tqdm(day_dirs, desc="SofaScore", unit="day"):
        day_key = f"sofa:{day_dir.name}"
        if day_key in checkpoint:
            continue

        events_file = day_dir / "events.json"
        if not events_file.exists():
            _mark_checkpoint(checkpoint_file, day_key)
            checkpoint.add(day_key)
            continue

        raw = json.loads(events_file.read_text(encoding="utf-8"))
        events = raw.get("events", [])

        day_matches = []
        day_sets = []
        for event in events:
            row = flatten_sofa_event(event)
            if not row.get("date"):
                t = row.get("start_time_utc", "")
                row["date"] = t[:10] if t else ""
            day_matches.append(row)

            for side in ("homeTeam", "awayTeam"):
                p = event.get(side, {})
                if p.get("id"):
                    all_players[p["id"]] = {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "slug": p.get("slug", ""),
                        "source": "sofascore",
                    }

            day_sets.extend(flatten_sofa_sets(row["event_id"], event))

        _append_csv(day_matches, match_path, MATCH_FIELDS)
        _append_csv(day_sets, set_path, SET_FIELDS)
        total_matches += len(day_matches)
        total_sets += len(day_sets)

        _mark_checkpoint(checkpoint_file, day_key)
        checkpoint.add(day_key)

    print(f"  SofaScore: {total_matches} matches, {total_sets} sets, {len(all_players)} players")
    return all_players, total_matches, total_sets


# ─── Flashscore flattening ─────────────────────────────────────────────────────

def flatten_flash_match(match: dict, date_str: str) -> dict:
    sets_data = match.get("sets", [])
    row = {
        "source": "flashscore",
        "event_id": match.get("match_id", ""),
        "date": date_str,
        "start_time_utc": f"{date_str} {match.get('time', '')}".strip(),
        "tournament_name": match.get("tournament", ""),
        "tournament_id": "",
        "round": "",
        "round_name": "",
        "status_code": "",
        "status_description": "finished",
        "home_id": "",
        "home_name": match.get("home_player", ""),
        "home_slug": "",
        "away_id": "",
        "away_name": match.get("away_player", ""),
        "away_slug": "",
        "home_sets_won": match.get("score_home", ""),
        "away_sets_won": match.get("score_away", ""),
        "winner": "",
    }

    # Fill in per-set scores
    for i, s in enumerate(sets_data[:7], start=1):
        row[f"home_set{i}"] = s.get("home", "")
        row[f"away_set{i}"] = s.get("away", "")

    for i in range(len(sets_data) + 1, 8):
        row[f"home_set{i}"] = ""
        row[f"away_set{i}"] = ""

    h = row["home_sets_won"]
    a = row["away_sets_won"]
    if h and a:
        try:
            row["winner"] = "home" if int(h) > int(a) else "away"
        except ValueError:
            pass

    return row


def flatten_flash_sets(match: dict, date_str: str) -> list[dict]:
    sets_data = match.get("sets", [])
    rows = []
    for i, s in enumerate(sets_data, start=1):
        h = s.get("home")
        a = s.get("away")
        rows.append({
            "source": "flashscore",
            "event_id": match.get("match_id", ""),
            "home_name": match.get("home_player", ""),
            "away_name": match.get("away_player", ""),
            "set_number": i,
            "home_points": h,
            "away_points": a,
            "set_winner": "home" if (h or "0") > (a or "0") else "away",
        })
    return rows


def process_flashscore(data_dir: Path, out_dir: Path, checkpoint: set, checkpoint_file: Path):
    total_matches = 0
    total_sets = 0

    flash_dir = data_dir / "flashscore"
    if not flash_dir.exists():
        print("  – No Flashscore data found.")
        return total_matches, total_sets

    day_dirs = sorted(flash_dir.iterdir())
    skipped = sum(1 for d in day_dirs if f"flash:{d.name}" in checkpoint)
    if skipped:
        print(f"  Resuming — skipping {skipped} already-processed days")

    match_path = out_dir / "matches.csv"
    set_path = out_dir / "sets.csv"

    for day_dir in tqdm(day_dirs, desc="Flashscore", unit="day"):
        day_key = f"flash:{day_dir.name}"
        if day_key in checkpoint:
            continue

        matches_file = day_dir / "matches.json"
        if not matches_file.exists():
            _mark_checkpoint(checkpoint_file, day_key)
            checkpoint.add(day_key)
            continue

        raw = json.loads(matches_file.read_text(encoding="utf-8"))
        date_str = raw.get("date", day_dir.name)

        day_matches = []
        day_sets = []
        for match in raw.get("matches", []):
            row = flatten_flash_match(match, date_str)
            day_matches.append(row)
            day_sets.extend(flatten_flash_sets(match, date_str))

        _append_csv(day_matches, match_path, MATCH_FIELDS)
        _append_csv(day_sets, set_path, SET_FIELDS)
        total_matches += len(day_matches)
        total_sets += len(day_sets)

        _mark_checkpoint(checkpoint_file, day_key)
        checkpoint.add(day_key)

    print(f"  Flashscore: {total_matches} matches, {total_sets} sets")
    return total_matches, total_sets


# ─── CSV writer ───────────────────────────────────────────────────────────────

MATCH_FIELDS = [
    "source", "event_id", "date", "start_time_utc",
    "tournament_name", "tournament_id", "round", "round_name",
    "status_code", "status_description",
    "home_id", "home_name", "home_slug",
    "away_id", "away_name", "away_slug",
    "home_sets_won", "away_sets_won",
    "home_set1", "away_set1",
    "home_set2", "away_set2",
    "home_set3", "away_set3",
    "home_set4", "away_set4",
    "home_set5", "away_set5",
    "home_set6", "away_set6",
    "home_set7", "away_set7",
    "winner",
]

SET_FIELDS = [
    "source", "event_id", "home_name", "away_name",
    "set_number", "home_points", "away_points", "set_winner",
]

PLAYER_FIELDS = ["id", "name", "slug", "source"]


def _append_csv(rows: list[dict], path: Path, fields: list[str]):
    """Append rows to CSV. Writes header automatically if the file is new."""
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_csv(rows: list[dict], path: Path, fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ Written {len(rows)} rows → {path}")


# ─── Checkpoint helpers ───────────────────────────────────────────────────────

def _load_checkpoint(path: Path) -> set:
    if not path.exists():
        return set()
    return set(path.read_text(encoding="utf-8").splitlines())


def _mark_checkpoint(path: Path, key: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(key + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Post-process raw TT scraper JSON → CSV")
    parser.add_argument("--data", default="./data", help="Raw data root (from tt_scraper.py)")
    parser.add_argument("--output", default="./processed", help="Output directory for CSVs")
    parser.add_argument("--resume", action="store_true",
                        help="Resume a previous interrupted run instead of starting fresh")
    args = parser.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_file = out_dir / ".checkpoint"

    if args.resume:
        checkpoint = _load_checkpoint(checkpoint_file)
        print(f"Resuming — {len(checkpoint)} days already processed.\n")
        # Load existing players so they aren't lost on a partial resume
        existing_players = {}
        player_path = out_dir / "players.csv"
        if player_path.exists():
            with open(player_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    existing_players[row["id"]] = row
    else:
        checkpoint = set()
        existing_players = {}
        # Clear outputs for a clean run
        for fname in ("matches.csv", "sets.csv", "players.csv", "matches_combined.json", ".checkpoint"):
            p = out_dir / fname
            if p.exists():
                p.unlink()

    print("Processing SofaScore …")
    sofa_players, sofa_matches, sofa_sets = process_sofascore(data_dir, out_dir, checkpoint, checkpoint_file)

    print("\nProcessing Flashscore …")
    flash_matches, flash_sets = process_flashscore(data_dir, out_dir, checkpoint, checkpoint_file)

    print("\nWriting players …")
    merged_players = {**existing_players, **sofa_players}
    write_csv(list(merged_players.values()), out_dir / "players.csv", PLAYER_FIELDS)

    # Build combined JSON from the completed matches CSV
    match_path = out_dir / "matches.csv"
    set_path = out_dir / "sets.csv"
    if match_path.exists():
        print("Building combined JSON …")
        with open(match_path, newline="", encoding="utf-8") as f:
            all_matches = list(csv.DictReader(f))
        set_count = sum(1 for _ in open(set_path, encoding="utf-8")) - 1 if set_path.exists() else 0
        combined = {
            "match_count": len(all_matches),
            "set_count": set_count,
            "player_count": len(merged_players),
            "matches": all_matches,
        }
        combined_path = out_dir / "matches_combined.json"
        combined_path.write_text(
            json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  ✓ Combined JSON → {combined_path}")

    print(f"\n✅ Done. Output in: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
