"""The Proper Player's public 2026 draw, scores and division ladders."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# These are the data.js and Firebase public score feed used by the league page.
SOURCE_URL = "https://tpp-6aside.netlify.app/"
LEAGUE_URL = "https://www.theproperplayer.com/6-a-side-league"
DRAW_URL = SOURCE_URL + "data.js"
RESULTS_URL = (
    "https://tpp-mindset-default-rtdb.asia-southeast1.firebasedatabase.app"
    "/sixaside2026/public.json"
)
CACHE = Path(__file__).resolve().parent / "docs" / "sixaside.json"
PLAYERS = {
    "finn": {"label": "Finn", "division": "U14", "team": "The Army"},
    "tate": {"label": "Tate", "division": "U12", "team": "The Academy"},
}
FINALS_DATE = "2026-12-14"


def read_public(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Finn-Tate-Sports-Calendar/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def decode_draw(script: str) -> dict[str, Any]:
    """Read the published JSON assignment without executing third-party code."""
    match = re.search(r"\bwindow\.LEAGUE\s*=\s*", script)
    if not match:
        raise ValueError("The league data assignment was not found")
    payload, end = json.JSONDecoder().raw_decode(script[match.end():])
    if script[match.end() + end:].strip() not in {"", ";"}:
        raise ValueError("Unexpected league data format")
    return payload


def normalise_draw(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid league draw")
    divisions = ["U12", "U14"]
    if any(d not in payload.get("divs", []) for d in divisions):
        raise ValueError("The U12 or U14 division is missing")
    teams = {}
    for player in PLAYERS.values():
        division = player["division"]
        entries = payload.get("teams", {}).get(division)
        if not isinstance(entries, list) or not any(
            t.get("name") == player["team"] for t in entries if isinstance(t, dict)
        ):
            raise ValueError(f"{player['team']} is missing from {division}")
        names = [t["name"] for t in entries]
        if len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
            raise ValueError("Invalid or duplicate league teams")
        teams[division] = [
            {"name": t["name"], "colour": str(t.get("colour") or "")}
            for t in entries
        ]

    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        raise ValueError("The league round dates are missing")
    for item in dates:
        datetime.strptime(item["date"], "%d/%m/%Y")
    games = []
    used_ids = set()
    if not isinstance(payload.get("games"), list):
        raise ValueError("The league fixtures are missing")
    for raw in payload["games"]:
        if raw.get("div") not in divisions:
            continue
        if not all(raw.get(k) for k in ("id", "round", "date", "home", "away")):
            raise ValueError("A league fixture is incomplete")
        if raw["id"] in used_ids:
            raise ValueError("Duplicate league fixture ID")
        used_ids.add(raw["id"])
        if str(raw["home"]).casefold() == "bye" or str(raw["away"]).casefold() == "bye":
            continue
        date = datetime.strptime(raw["date"], "%d/%m/%Y")
        time_text = str(raw.get("time") or "").strip()
        if time_text and time_text.casefold() not in {"tbc", "tbd", "time tbc"}:
            time = datetime.strptime(time_text.upper(), "%I:%M %p")
            date = date.replace(hour=time.hour, minute=time.minute)
        else:
            time_text = ""
        if date.year != 2026:
            raise ValueError("Unexpected six-a-side season")
        game = {k: raw[k] for k in (
            "id", "round", "date", "pitch", "div", "home", "away",
            "bonus", "changed", "was", "status",
        ) if k in raw}
        game.update(time=time_text, start=date.replace(tzinfo=ZoneInfo("Australia/Perth")).isoformat())
        games.append(game)
    if any(not any(g["div"] == d for g in games) for d in divisions):
        raise ValueError("The draw must include both boys' divisions")
    for player in PLAYERS.values():
        if not any(g["div"] == player["division"] and player["team"] in (g["home"], g["away"]) for g in games):
            raise ValueError(f"The online draw has no games for {player['team']}")
    byes = payload.get("byes", [])
    if not isinstance(byes, list):
        raise ValueError("Invalid league byes")
    return {
        "divs": divisions,
        "labels": {d: payload.get("labels", {}).get(d, d) for d in divisions},
        "teams": teams,
        "games": sorted(games, key=lambda g: (g["start"], g["div"], str(g.get("pitch", "")), g["id"])),
        "byes": [dict(b) for b in byes if b.get("div") in divisions],
        "dates": dates,
        "changes": [dict(c) for c in payload.get("changes", []) if c.get("div") in divisions],
        "generated": str(payload.get("generated") or ""),
    }


def normalise_results(payload: Any, draw: dict[str, Any]) -> dict[str, dict[str, int]]:
    # Firebase returns null before the first score has been entered.
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("Invalid public score response")
    result = {}
    for game in draw["games"]:
        raw = payload.get(game["id"])
        if raw is None:
            continue
        if not isinstance(raw, dict) or any(
            type(raw.get(k)) is not int or raw[k] < 0 for k in ("h", "a")
        ):
            raise ValueError(f"Invalid score for {game['id']}")
        result[game["id"]] = {"h": raw["h"], "a": raw["a"]}
    return dict(sorted(result.items()))


def division_ladder(draw: dict[str, Any], results: dict[str, Any], division: str) -> dict[str, Any]:
    """Use the league's exact scoring and tie-break order."""
    rows = {
        t["name"]: {"team": t["name"], "played": 0, "won": 0, "drawn": 0,
                    "lost": 0, "for": 0, "against": 0, "points": 0}
        for t in draw["teams"][division]
    }
    games = [g for g in draw["games"] if g["div"] == division]
    played = 0
    for game in games:
        score = results.get(game["id"])
        if score is None or game["home"] not in rows or game["away"] not in rows:
            continue
        # The official ladder counts every scored game, including bonus games.
        home, away = rows[game["home"]], rows[game["away"]]
        h, a = score["h"], score["a"]
        played += 1
        home["played"] += 1
        away["played"] += 1
        home["for"] += h
        home["against"] += a
        away["for"] += a
        away["against"] += h
        if h > a:
            home["won"] += 1
            away["lost"] += 1
            home["points"] += 3
        elif a > h:
            away["won"] += 1
            home["lost"] += 1
            away["points"] += 3
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    ordered = sorted(rows.values(), key=lambda r: (
        -r["points"], -(r["for"] - r["against"]), -r["for"], r["team"].casefold(),
    ))
    for position, row in enumerate(ordered, 1):
        row.update(position=position, difference=row["for"] - row["against"])
    return {"division": division, "label": draw["labels"][division],
            "rows": ordered, "played": played, "total": len(games)}


def fixture_round(fixture: dict[str, Any]) -> str:
    value = str(fixture.get("round", ""))
    if "final" in value.casefold() or str(fixture.get("start", "")).startswith(FINALS_DATE):
        return "10"
    return value


def fixture_pair(fixture: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((fixture["home"].casefold(), fixture["away"].casefold())))


def calendar_records(draw: dict[str, Any], results: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    old_records = previous.get("calendar_fixtures", [])
    records = []
    assigned = set()
    for player in PLAYERS.values():
        label, division, team = player["label"], player["division"], player["team"]
        kit = next(t["colour"] for t in draw["teams"][division] if t["name"] == team)
        games = [g for g in draw["games"] if g["div"] == division and team in (g["home"], g["away"])]
        if not games:
            raise ValueError(f"The online draw has no games for {team}")
        incoming = []
        for game in games:
            score = results.get(game["id"], {})
            notes = (f"{division} — {team}. Kit: {kit}; shin pads required. "
                     "2 × 18-minute halves; calendar reserves 45 minutes including half-time.")
            if game.get("bonus"):
                notes += " Bonus game."
            if game.get("changed"):
                notes += f" Fixture changed {game['changed']}."
                if game.get("was"):
                    notes += f" Previously: {game['was']}."
            timed = bool(game["time"])
            if not timed:
                notes += " Kick-off time has not been published."
            cancelled = str(game.get("status", "")).casefold() in {"cancelled", "canceled"}
            incoming.append({
                "label": label, "division": division, "source_id": game["id"],
                "source_type": "proper_player_sixaside", "source_url": SOURCE_URL,
                "start": game["start"], "home": game["home"], "away": game["away"],
                "venue": "Rossiter Pavilion, Piara Waters", "field": f"Pitch {game.get('pitch') or 'TBC'}",
                "round": str(game["round"]), "sport_icon": "⚽", "sport_name": "6-a-side Soccer",
                "time_label": "KO", "all_day": not timed, "duration_minutes": 45,
                "reminder_minutes": 90 if timed else 0,
                "status": "CANCELLED" if cancelled else "CONFIRMED" if timed else "TENTATIVE",
                "notes": notes, "display_title": f"{division} {game['home']} vs {game['away']} — 6-a-side",
                "home_score": str(score["h"]) if score else "",
                "away_score": str(score["a"]) if score else "",
            })
        if not any(fixture_round(g) == "10" for g in incoming):
            incoming.append({
                "label": label, "division": division, "source_id": f"2026-{division}-{label}-finals-placeholder",
                "source_type": "proper_player_sixaside", "source_url": SOURCE_URL,
                "start": FINALS_DATE + "T17:00:00+08:00", "home": team, "away": "Opponent TBC",
                "venue": "Rossiter Pavilion, Piara Waters", "field": "Pitch TBC",
                "round": "Finals and placing games — Placeholder", "sport_icon": "⚽", "sport_name": "6-a-side Soccer",
                "time_label": "Window from", "time_window": "5pm–8pm · finals kick-off TBC",
                "duration_minutes": 180, "reminder_minutes": 90, "all_day": False,
                "status": "TENTATIVE", "display_title": f"{division} {team} — 6-a-side finals / placing — Placeholder",
                "notes": (f"Finals and placing games on Monday 14 December. Draw published after Round 9. "
                          f"{division} {team}. Kit: {kit}; shin pads required. "
                          "5pm–8pm is a provisional window; kick-off, opponent and pitch TBC."),
                "home_score": "", "away_score": "",
            })
        for fixture in incoming:
            candidates = [o for o in old_records if o.get("label") == label
                          and fixture_round(o) == fixture_round(fixture) and o.get("uid") not in assigned]
            exact = next((o for o in candidates if fixture_pair(o) == fixture_pair(fixture)), None)
            # A sole fixture in a round can change opponent as well as time/pitch.
            if exact is None and len(candidates) == 1 and (
                sum(fixture_round(f) == fixture_round(fixture) for f in incoming) == 1
                or candidates[0].get("status") == "TENTATIVE" and fixture_round(fixture) == "10"
            ):
                exact = candidates[0]
            seed = "|".join(("proper-player", "2026", label, division, fixture_round(fixture), *fixture_pair(fixture)))
            fixture["uid"] = exact["uid"] if exact else hashlib.sha256(seed.encode()).hexdigest()[:24] + "@family-soccer-calendar"
            if fixture["uid"] in assigned:
                raise ValueError("Duplicate six-a-side calendar identity")
            assigned.add(fixture["uid"])
            records.append(fixture)
    # Explicit cancellations remove withdrawn games from subscribed calendars.
    for old in old_records:
        if old.get("uid") in assigned:
            continue
        cancelled = dict(old)
        if not cancelled.get("removed"):
            cancelled["notes"] = str(cancelled.get("notes") or "") + " Removed from the published league draw."
        cancelled.update(status="CANCELLED", removed=True)
        records.append(cancelled)
    return sorted(records, key=lambda f: (f["start"], f["label"], f["uid"]))


def prepare_snapshot(payload: dict[str, Any], scores: Any, previous: dict[str, Any] | None = None,
                     draw_status: str = "available", results_status: str = "available") -> dict[str, Any]:
    draw = normalise_draw(payload)
    results = normalise_results(scores, draw)
    return {
        "schema_version": 1, "season": "2026", "timezone": "Australia/Perth",
        "source_url": SOURCE_URL, "league_url": LEAGUE_URL,
        "draw_status": draw_status, "results_status": results_status,
        "players": PLAYERS, "draw": draw, "results": results,
        "ladders": [division_ladder(draw, results, d) for d in draw["divs"]],
        "calendar_fixtures": calendar_records(draw, results, previous or {}),
    }


def parse_sixaside_fixtures(snapshot: dict[str, Any], timezone: ZoneInfo) -> list[dict[str, Any]]:
    if snapshot.get("schema_version") != 1 or snapshot.get("timezone") != "Australia/Perth":
        raise ValueError("Invalid cached six-a-side fixtures")
    fixtures = []
    for record in snapshot["calendar_fixtures"]:
        fixture = dict(record)
        fixture["start"] = datetime.fromisoformat(record["start"]).astimezone(timezone)
        if not fixture.get("uid") or fixture.get("label") not in {"Finn", "Tate"}:
            raise ValueError("Invalid six-a-side calendar identity")
        fixtures.append(fixture)
    return fixtures


def refresh_sixaside_fixtures(timezone: ZoneInfo) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Refresh draw and scores independently; retain published data on outages."""
    previous = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    warnings = []
    draw_status = results_status = "available"
    try:
        draw = normalise_draw(decode_draw(read_public(DRAW_URL)))
    except Exception as exc:
        if not previous:
            raise
        warnings.append(f"Draw: {exc}")
        draw = previous["draw"]
        draw_status = "cached"
    try:
        scores = normalise_results(json.loads(read_public(RESULTS_URL)), draw)
    except Exception as exc:
        if not previous:
            raise
        warnings.append(f"Scores: {exc}")
        scores = previous["results"]
        results_status = "cached"
    try:
        snapshot = prepare_snapshot(draw, scores, previous, draw_status, results_status)
    except Exception as exc:
        if not previous:
            raise
        warnings.append(f"Fixture validation: {exc}")
        snapshot = dict(previous, draw_status="cached", results_status="cached")
    fixtures = parse_sixaside_fixtures(snapshot, timezone)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if warnings:
        print("The Proper Player warning: " + "; ".join(warnings))
    return fixtures, {"source": SOURCE_URL, "fixture_count": len(fixtures),
                      "result_count": len(snapshot["results"]), "used_cache": bool(warnings),
                      "warnings": warnings}
