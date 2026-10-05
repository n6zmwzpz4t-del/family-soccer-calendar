"""Tate's published Thornlie & Districts TeeBall fixtures and cached refresh."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TEAM_ID = "0a4018f8-8cd1-4eb4-927d-c19967ef6b90"
TEAM_NAME = "Harrisdale Hawks Challenge Shopfitters U13s"
SOURCE_URL = f"https://thornliedistricts.com/fixtures?team={TEAM_ID}"
API_URL = f"https://thornliedistricts.com/api/public/fixtures?team={TEAM_ID}"
CACHE = Path(__file__).resolve().parent / "docs" / "teeball.json"


def prepare_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only the exact team and stable published fields, never other clubs."""
    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise ValueError("Invalid TeeBall fixture response")
    selection = payload.get("selection") or {}
    if selection.get("team") != TEAM_ID and payload.get("team_id") != TEAM_ID:
        raise ValueError("Fixture response is not for Tate's team")
    if payload.get("timezone", "Australia/Perth") != "Australia/Perth":
        raise ValueError("Unexpected TeeBall fixture timezone")
    selected = [
        dict(f) for f in payload["fixtures"]
        if TEAM_ID in (f.get("homeTeamId"), f.get("awayTeamId"))
    ]
    # A non-empty response with no exact team match must not erase the cache.
    if payload["fixtures"] and not selected:
        raise ValueError("No fixtures match Tate's exact team ID")
    snapshot = {
        "season": payload.get("season", "2026/27 Season"),
        "timezone": "Australia/Perth",
        "team_id": TEAM_ID,
        "team_name": TEAM_NAME,
        "source_url": SOURCE_URL,
        # The source generates a new timestamp per request; omit it so an
        # unchanged draw does not cause a deployment on every refresh.
        "fixtures": sorted(selected, key=lambda f: (f.get("date", ""), f.get("time") or "")),
    }
    parse_teeball_fixtures(snapshot, ZoneInfo("Australia/Perth"))
    return snapshot


def parse_teeball_fixtures(
    snapshot: dict[str, Any], timezone: ZoneInfo,
) -> list[dict[str, Any]]:
    fixtures = []
    used_ids = set()
    for item in snapshot["fixtures"]:
        home = str(item.get("homeTeam", "")).strip()
        away = str(item.get("awayTeam", "")).strip()
        status = str(item.get("status", "scheduled")).casefold()
        if status == "bye" or home.casefold() == "bye" or away.casefold() == "bye":
            continue
        if not home or not away:
            raise ValueError("TeeBall fixture is missing a team")
        time = str(item.get("time") or "").strip()
        start = datetime.fromisoformat(
            str(item["date"]) + "T" + (time or "00:00")
        ).replace(tzinfo=timezone)
        round_name = str(item.get("round") or "Round TBC").strip()
        source_id = "|".join([
            "thornlie-teeball", str(snapshot["season"]), round_name,
            str(item["homeTeamId"]), str(item["awayTeamId"]),
        ])
        if source_id in used_ids:
            raise ValueError("Duplicate TeeBall fixture identity")
        used_ids.add(source_id)
        uid = hashlib.sha256(source_id.encode()).hexdigest()[:24] + "@family-soccer-calendar"
        ground = str(item.get("ground") or "Venue TBC").strip()
        venue = (
            "Sutherlands Park, Huntingdale"
            if ground.casefold() in {"sutherlands oval", "sutherlands park"}
            else ground
        )
        notes = f"Under 13 — {TEAM_NAME}. {snapshot['season']}. Playing time: 60 minutes."
        if start.weekday() == 4 and time == "17:00":
            notes += " Friday game: arrive by 4:30pm."
        if not time:
            notes += " Start time has not been published."
        cancelled = status in {"cancelled", "canceled"}
        fixtures.append({
            "label": "Tate", "source_id": source_id, "uid": uid,
            "source_type": "thornlie_teeball", "source_url": SOURCE_URL,
            "start": start, "home": home, "away": away,
            "venue": venue, "field": str(item.get("diamond") or "Diamond TBC"),
            "round": round_name, "sport_icon": "🥎", "sport_name": "TeeBall",
            "time_label": "Start", "all_day": not bool(time),
            "duration_minutes": 60, "reminder_minutes": 90 if time else 0,
            "status": "CANCELLED" if cancelled else "CONFIRMED" if time else "TENTATIVE",
            "notes": notes, "latitude": None, "longitude": None,
            "home_score": str(item.get("homeScore") if item.get("homeScore") is not None else ""),
            "away_score": str(item.get("awayScore") if item.get("awayScore") is not None else ""),
        })
    return fixtures


def refresh_teeball_fixtures(
    timezone: ZoneInfo,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Refresh the public draw; retain the last valid draw during outages."""
    warning = ""
    try:
        request = Request(API_URL, headers={"User-Agent": "Finn-Tate-Sports-Calendar/1.0"})
        with urlopen(request, timeout=30) as response:
            snapshot = prepare_snapshot(json.load(response))
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        warning = str(exc)
        print(f"Thornlie TeeBall warning: {warning}; using the published cache.")
        snapshot = prepare_snapshot(json.loads(CACHE.read_text(encoding="utf-8")))
    fixtures = parse_teeball_fixtures(snapshot, timezone)
    return fixtures, {
        "source": SOURCE_URL, "team_id": TEAM_ID,
        "fixture_count": len(fixtures), "used_cache": bool(warning), "warning": warning,
    }
