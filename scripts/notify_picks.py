"""Send evidence-gated event previews and daily paper picks to configured webhooks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import argparse

import requests

ROOT = Path(__file__).parent.parent
UPCOMING_PATH = ROOT / "processed" / "upcoming_enriched.json"


def top_pick() -> dict[str, object] | None:
    if not UPCOMING_PATH.exists():
        return None
    fixtures = json.loads(UPCOMING_PATH.read_text(encoding="utf-8")).get("fixtures", [])
    eligible = [
        f for f in fixtures
        if f.get("_conf_label") == "High" and f.get("Coverage Tier") in {"High", "Medium"}
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: float(str(row.get("Win %", "0")).rstrip("%") or 0))


def preview_text(pick: dict[str, object]) -> str:
    return (
        f"Pong Odds paper pick: {pick.get('Favourite')} in {pick.get('Tournament')} — "
        f"model {pick.get('Win %')}, {pick.get('Confidence')}, coverage {pick.get('Coverage Tier')}. "
        f"Context: {pick.get('Model Explain', 'historical model factors')}. Paper-only; no staking advice."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discord-only", action="store_true")
    parser.add_argument("--email-only", action="store_true")
    args = parser.parse_args()
    pick = top_pick()
    if not pick:
        print("No eligible high-confidence paper pick")
        return
    text = preview_text(pick)
    discord = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    email_webhook = os.getenv("EMAIL_WEBHOOK_URL", "").strip()
    if discord and not args.email_only:
        response = requests.post(discord, json={"content": text}, timeout=20)
        response.raise_for_status()
        print("Discord paper pick sent")
    if email_webhook and not args.discord_only:
        response = requests.post(
            email_webhook,
            json={"subject": "Pong Odds event-week preview", "text": text, "pick": pick},
            timeout=20,
        )
        response.raise_for_status()
        print("Event preview webhook sent")
    if (not discord or args.email_only) and (not email_webhook or args.discord_only):
        print(text)


if __name__ == "__main__":
    main()
